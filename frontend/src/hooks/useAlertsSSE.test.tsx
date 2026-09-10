import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'

const { warning } = vi.hoisted(() => ({ warning: vi.fn() }))
vi.mock('sonner', () => ({ toast: { warning } }))

import { useAlertsSSE } from './useAlertsSSE'
import { useAuthStore } from '@/stores/auth.store'

class FakeEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static instances: FakeEventSource[] = []

  readonly url: string
  readyState = FakeEventSource.OPEN
  onerror: (() => void) | null = null
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
}

function AlertsSSEHarness() {
  useAlertsSSE()
  return null
}

describe('useAlertsSSE — US-20 cliente en tiempo real', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    warning.mockReset()
    vi.stubGlobal('EventSource', FakeEventSource)
    useAuthStore.setState({
      accessToken: 'token con espacios',
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
      isLoading: false,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })

  it('abre el stream autenticado y una alerta muestra una notificación sin recargar e invalida las vistas relacionadas', async () => {
    const { queryClient } = renderWithProviders(<AlertsSSEHarness />)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0].url).toContain('/alerts/stream?token=token%20con%20espacios')

    act(() => {
      FakeEventSource.instances[0].emit('alert', JSON.stringify({ event_id: 42, severity: 'critical' }))
    })

    expect(warning).toHaveBeenCalledWith('Alerta critical — evento #42')
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts'] }))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts-failed-count'] })
  })

  it('ante un cierre definitivo cierra el stream vencido e intenta renovar la sesión', async () => {
    const refreshToken = vi.fn().mockResolvedValue(undefined)
    useAuthStore.setState({ refreshToken })
    renderWithProviders(<AlertsSSEHarness />)

    const source = FakeEventSource.instances[0]
    source.readyState = FakeEventSource.CLOSED
    act(() => source.onerror?.())

    expect(source.close).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(refreshToken).toHaveBeenCalledTimes(1))
  })
})
