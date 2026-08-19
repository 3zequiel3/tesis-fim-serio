import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
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
