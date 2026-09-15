import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'

const { warning } = vi.hoisted(() => ({ warning: vi.fn() }))
vi.mock('sonner', () => ({ toast: { warning } }))

const { fetchStreamTicket } = vi.hoisted(() => ({ fetchStreamTicket: vi.fn() }))
vi.mock('@/api/alerts', () => ({ fetchStreamTicket }))

import { useAlertsSSE } from './useAlertsSSE'
import { useAuthStore } from '@/stores/auth.store'

class FakeEventSource {
  static instances: FakeEventSource[] = []

  readonly url: string
  onerror: (() => void) | null = null
  onopen: (() => void) | null = null
  close = vi.fn()
  private listeners = new Map<string, (event: MessageEvent) => void>()

  constructor(url: string | URL) {
    this.url = String(url)
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    this.listeners.set(type, listener as (event: MessageEvent) => void)
  }

  emit(type: string, data: string) {
    this.listeners.get(type)?.({ data } as MessageEvent)
  }

  open() {
    this.onopen?.()
  }

  error() {
    this.onerror?.()
  }
}

function AlertsSSEHarness() {
  useAlertsSSE()
  return null
}

function axiosError(status: number) {
  return { response: { status } }
}

async function flush() {
  // Deja correr las promesas encoladas por connect() (fetchStreamTicket es
  // async) sin avanzar los fake timers.
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('useAlertsSSE — ticket SSE de un solo uso (D64/RN-158)', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    warning.mockReset()
    fetchStreamTicket.mockReset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.useFakeTimers()
    useAuthStore.setState({
      accessToken: 'access-token-1',
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
      isLoading: false,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })

  it('pide un ticket antes de abrir el EventSource; la URL contiene ticket= y no token= ni el access token', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt-1', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(1)
    expect(FakeEventSource.instances).toHaveLength(1)
    const url = FakeEventSource.instances[0].url
    expect(url).toContain('ticket=tkt-1')
    expect(url).not.toContain('token=')
    expect(url).not.toContain('access-token-1')
  })

  it('una alerta nueva muestra un toast e invalida alerts, dashboard y alerts/failed/count', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt-1', expires_in: 30 })
    const { queryClient } = renderWithProviders(<AlertsSSEHarness />)
    await flush()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    act(() => {
      FakeEventSource.instances[0].emit(
        'alert',
        JSON.stringify({ id: 9, event_id: 42, severity: 'critical' }),
      )
    })

    expect(warning).toHaveBeenCalledWith('Alerta critical — evento #42')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts', 'failed', 'count'] })
  })

  it('reconexión sin pérdida: tras una alerta con id 9, onerror cierra y reabre con ticket nuevo y last_event_id=9', async () => {
    fetchStreamTicket
      .mockResolvedValueOnce({ ticket: 'tkt-1', expires_in: 30 })
      .mockResolvedValueOnce({ ticket: 'tkt-2', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    act(() => {
      FakeEventSource.instances[0].emit('alert', JSON.stringify({ id: 9, severity: 'high' }))
    })

    act(() => {
      FakeEventSource.instances[0].error()
    })
    expect(FakeEventSource.instances[0].close).toHaveBeenCalledTimes(1)

    // Backoff inicial: 1s
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(2)
    expect(FakeEventSource.instances).toHaveLength(2)
    expect(FakeEventSource.instances[1].url).toContain('ticket=tkt-2')
    expect(FakeEventSource.instances[1].url).toContain('last_event_id=9')
  })

  it('reconexión sin alertas previas: la URL nueva no contiene last_event_id', async () => {
    fetchStreamTicket
      .mockResolvedValueOnce({ ticket: 'tkt-1', expires_in: 30 })
      .mockResolvedValueOnce({ ticket: 'tkt-2', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    act(() => {
      FakeEventSource.instances[0].error()
    })
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    await flush()

    expect(FakeEventSource.instances).toHaveLength(2)
    expect(FakeEventSource.instances[1].url).not.toContain('last_event_id')
  })

  it('backoff exponencial acotado a 30s y reiniciado tras una apertura exitosa', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    // 1er error -> espera 1s
    act(() => FakeEventSource.instances[0].error())
    await act(async () => vi.advanceTimersByTime(999))
    expect(FakeEventSource.instances).toHaveLength(1)
    await act(async () => vi.advanceTimersByTime(1))
    await flush()
    expect(FakeEventSource.instances).toHaveLength(2)

    // 2do error -> espera 2s
    act(() => FakeEventSource.instances[1].error())
    await act(async () => vi.advanceTimersByTime(1999))
    expect(FakeEventSource.instances).toHaveLength(2)
    await act(async () => vi.advanceTimersByTime(1))
    await flush()
    expect(FakeEventSource.instances).toHaveLength(3)

    // 3er error -> espera 4s
    act(() => FakeEventSource.instances[2].error())
    await act(async () => vi.advanceTimersByTime(3999))
    expect(FakeEventSource.instances).toHaveLength(3)
    await act(async () => vi.advanceTimersByTime(1))
    await flush()
    expect(FakeEventSource.instances).toHaveLength(4)

    // Apertura exitosa reinicia el backoff a 1s.
    act(() => FakeEventSource.instances[3].open())
    act(() => FakeEventSource.instances[3].error())
    await act(async () => vi.advanceTimersByTime(999))
    expect(FakeEventSource.instances).toHaveLength(4)
    await act(async () => vi.advanceTimersByTime(1))
    await flush()
    expect(FakeEventSource.instances).toHaveLength(5)
  })

  it('cap de 30s: tras varios errores consecutivos el intervalo nunca supera 30s', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    // 1,2,4,8,16 -> el próximo (6to error) debería toparse en 30s, no 32s.
    const delays = [1000, 2000, 4000, 8000, 16000]
    for (const delay of delays) {
      act(() => FakeEventSource.instances[FakeEventSource.instances.length - 1].error())
      await act(async () => vi.advanceTimersByTime(delay))
      await flush()
    }
    const countBeforeCap = FakeEventSource.instances.length

    act(() => FakeEventSource.instances[FakeEventSource.instances.length - 1].error())
    await act(async () => vi.advanceTimersByTime(29_999))
    expect(FakeEventSource.instances).toHaveLength(countBeforeCap)
    await act(async () => vi.advanceTimersByTime(1))
    await flush()
    expect(FakeEventSource.instances).toHaveLength(countBeforeCap + 1)
  })

  it('invalida las queries en una reapertura (no en la primera apertura)', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt', expires_in: 30 })
    const { queryClient } = renderWithProviders(<AlertsSSEHarness />)
    await flush()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    // Primera apertura: no debe invalidar nada por sí sola.
    act(() => FakeEventSource.instances[0].open())
    expect(invalidate).not.toHaveBeenCalled()

    act(() => FakeEventSource.instances[0].error())
    await act(async () => vi.advanceTimersByTime(1000))
    await flush()

    // Reapertura (segunda vez): invalida las tres queries.
    act(() => FakeEventSource.instances[1].open())
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts', 'failed', 'count'] })
  })

  it('401 al pedir el ticket detiene los reintentos', async () => {
    fetchStreamTicket.mockRejectedValue(axiosError(401))
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    expect(FakeEventSource.instances).toHaveLength(0)
    await act(async () => vi.advanceTimersByTime(60_000))
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(1)
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('403 al pedir el ticket detiene los reintentos', async () => {
    fetchStreamTicket.mockRejectedValue(axiosError(403))
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    await act(async () => vi.advanceTimersByTime(60_000))
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(1)
  })

  it('un error de red al pedir el ticket sí reintenta con backoff', async () => {
    fetchStreamTicket
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce({ ticket: 'tkt', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()

    expect(FakeEventSource.instances).toHaveLength(0)
    await act(async () => vi.advanceTimersByTime(1000))
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(2)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('la rotación del access token no reabre el stream', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt', expires_in: 30 })
    renderWithProviders(<AlertsSSEHarness />)
    await flush()
    expect(FakeEventSource.instances).toHaveLength(1)

    act(() => {
      useAuthStore.setState({ accessToken: 'access-token-2' })
    })
    await flush()

    expect(fetchStreamTicket).toHaveBeenCalledTimes(1)
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0].close).not.toHaveBeenCalled()
  })

  it('el desmontaje cancela el reintento pendiente', async () => {
    fetchStreamTicket.mockResolvedValue({ ticket: 'tkt', expires_in: 30 })
    const { unmount } = renderWithProviders(<AlertsSSEHarness />)
    await flush()

    act(() => FakeEventSource.instances[0].error())
    expect(FakeEventSource.instances[0].close).toHaveBeenCalledTimes(1)

    unmount()
    await act(async () => vi.advanceTimersByTime(60_000))
    await flush()

    // El único close() es el del error — el cleanup no encuentra una source
    // viva para cerrar de nuevo, y el timer pendiente no dispara un connect().
    expect(fetchStreamTicket).toHaveBeenCalledTimes(1)
    expect(FakeEventSource.instances).toHaveLength(1)
  })
})
