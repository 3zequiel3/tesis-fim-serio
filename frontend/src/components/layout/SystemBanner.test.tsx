import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { SystemBanner } from './SystemBanner'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

interface HealthOverrides {
  postgres?: string
  valkey?: string
  n8n?: string
  agents?: string
}

function mockHealth(overrides: HealthOverrides = {}) {
  const health = { postgres: 'ok', valkey: 'ok', n8n: 'ok', agents: 'ok', ...overrides }
  apiGet.mockImplementation((url: string) => {
    if (url !== '/health/components') throw new Error(`URL no mockeada en el test: ${url}`)
    return Promise.resolve({
      data: {
        postgres: health.postgres,
        valkey: health.valkey,
        n8n: health.n8n,
        agents: { status: health.agents, items: [] },
        checked_at: '2026-08-19T00:00:00Z',
      },
    })
  })
}

// US-05, criterio del banner rojo (detalle en US-28).
describe('SystemBanner — US-05: banner rojo de degradacion', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('no muestra ningun banner cuando todos los componentes estan ok', async () => {
    mockHealth()

    renderWithProviders(<SystemBanner />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/health/components'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('muestra un banner rojo que nombra el componente degradado', async () => {
    mockHealth({ valkey: 'down' })

    renderWithProviders(<SystemBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/sistema degradado/i)
    expect(banner).toHaveTextContent(/valkey/)
    expect(banner.className).toMatch(/bg-red-/)
  })

  it('trata al subsistema de agentes como degradado cuando su status no es ok', async () => {
    mockHealth({ agents: 'degraded' })

    renderWithProviders(<SystemBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/agents/)
  })

  it('nombra todos los componentes caidos a la vez', async () => {
    mockHealth({ postgres: 'down', n8n: 'down' })

    renderWithProviders(<SystemBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/postgres/)
    expect(banner).toHaveTextContent(/n8n/)
    expect(banner).not.toHaveTextContent(/valkey/)
  })
})

// US-28: poll cadence, timestamp del ultimo check saludable, dismiss + reappear,
// y que el banner no bloquee la UI.
describe('SystemBanner — US-28: banner de degradacion del sistema', () => {
  beforeEach(() => {
    apiGet.mockReset()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Cada respuesta de la cola lleva su propio checked_at, para poder
  // distinguir "el poll actual" de "el ultimo poll saludable".
  function mockHealthQueue(responses: Array<HealthOverrides & { checked_at: string }>) {
    let call = 0
    apiGet.mockImplementation((url: string) => {
      if (url !== '/health/components') throw new Error(`URL no mockeada en el test: ${url}`)
      const next = responses[Math.min(call, responses.length - 1)]
      call += 1
      return Promise.resolve({
        data: {
          postgres: next.postgres ?? 'ok',
          valkey: next.valkey ?? 'ok',
          n8n: next.n8n ?? 'ok',
          agents: { status: next.agents ?? 'ok', items: [] },
          checked_at: next.checked_at,
        },
      })
    })
  }

  it('consulta GET /health/components cada 10 segundos', async () => {
    mockHealthQueue([{ checked_at: '2026-08-19T00:00:00Z' }])

    renderWithProviders(<SystemBanner />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(3))

    // Sin haber avanzado 10s adicionales, no debe haber un 4to poll.
    expect(apiGet).toHaveBeenCalledTimes(3)
  })

  it('muestra el timestamp del ultimo check saludable del componente afectado', async () => {
    mockHealthQueue([
      { checked_at: '2026-08-19T00:00:00Z' }, // todo ok
      { checked_at: '2026-08-19T00:00:10Z', valkey: 'down' }, // se degrada
    ])

    renderWithProviders(<SystemBanner />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/valkey/)
    // El timestamp mostrado es el del ultimo poll SANO (00:00:00), no el
    // del poll degradado actual (00:00:10).
    expect(banner).toHaveTextContent('2026-08-19T00:00:00Z')
  })

  it('es cerrable manualmente y reaparece en el siguiente poll si la condicion persiste', async () => {
    mockHealthQueue([
      { checked_at: '2026-08-19T00:00:00Z', valkey: 'down' },
      { checked_at: '2026-08-19T00:00:10Z', valkey: 'down' },
    ])

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync })
    renderWithProviders(<SystemBanner />)

    const banner = await screen.findByRole('alert')
    const closeButton = await screen.findByRole('button', { name: /cerrar/i })

    await user.click(closeButton)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(banner).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })

    // Mismo componente sigue caido en el poll siguiente -> reaparece.
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('no bloquea el uso normal de la UI (no es overlay ni modal)', async () => {
    mockHealthQueue([{ checked_at: '2026-08-19T00:00:00Z', valkey: 'down' }])

    renderWithProviders(<SystemBanner />)

    const banner = await screen.findByRole('alert')
    // Un banner que bloquea la UI se implementaria como overlay fijo o
    // absoluto cubriendo la pantalla; este vive en el flujo normal.
    expect(banner.className).not.toMatch(/\b(fixed|absolute)\b/)
    expect(banner).not.toHaveAttribute('aria-modal')
  })
})
