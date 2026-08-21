import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { Dashboard } from './Dashboard'
import type { EventStatus } from '@/api/events'
import type { AgentStatus } from '@/api/agents'

// ─── Mock del cliente HTTP ────────────────────────────────────────────────────
// Se mockea `@/api/client` (no `@/api/dashboard`) para que el test ejercite la
// agregacion real del cliente: la pagina no tiene endpoint de dashboard, arma
// las metricas con N requests a /events (una por estado) + /agents + /health.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const CANONICAL_EVENT_STATUSES: EventStatus[] = [
  'pending',
  'approved',
  'rejected',
  'superseded',
  'auto_restored',
  'quarantined',
  'alert_only',
]

interface BackendState {
  eventCounts: Partial<Record<EventStatus, number>>
  pendingCriticalHigh: number
  agents: AgentStatus[]
  health: { postgres: string; valkey: string; n8n: string; agents: string }
}

const DEFAULT_STATE: BackendState = {
  eventCounts: {
    pending: 7,
    approved: 12,
    rejected: 3,
    superseded: 5,
    auto_restored: 2,
    quarantined: 1,
    alert_only: 4,
  },
  pendingCriticalHigh: 0,
  agents: ['online', 'online', 'offline', 'draining', 'dead'],
  health: { postgres: 'ok', valkey: 'ok', n8n: 'ok', agents: 'ok' },
}

type GetConfig = { params?: Record<string, unknown> | URLSearchParams } | undefined

function mockBackend(overrides: Partial<BackendState> = {}) {
  const state: BackendState = {
    ...DEFAULT_STATE,
    ...overrides,
    eventCounts: { ...DEFAULT_STATE.eventCounts, ...(overrides.eventCounts ?? {}) },
  }

  apiGet.mockImplementation((url: string, config: GetConfig) => {
    if (url === '/agents') {
      return Promise.resolve({
        data: { items: state.agents.map((status) => ({ status })), total: state.agents.length },
      })
    }
    if (url === '/health/components') {
      return Promise.resolve({
        data: {
          postgres: state.health.postgres,
          valkey: state.health.valkey,
          n8n: state.health.n8n,
          agents: { status: state.health.agents, items: [] },
          checked_at: '2026-08-19T00:00:00Z',
        },
      })
    }
    if (url === '/events') {
      // La request de severidad viaja como URLSearchParams (parametro repetible).
      if (config?.params instanceof URLSearchParams) {
        return Promise.resolve({ data: { total: state.pendingCriticalHigh } })
      }
      const status = (config?.params as Record<string, unknown> | undefined)?.status as EventStatus
      return Promise.resolve({ data: { total: state.eventCounts[status] ?? 0 } })
    }
    throw new Error(`URL no mockeada en el test: ${url}`)
  })

  return state
}

/** Estados de evento que la pagina realmente le pidio al backend. */
function queriedEventStatuses(): string[] {
  return apiGet.mock.calls
    .filter(([url, config]: [string, GetConfig]) => url === '/events' && !(config?.params instanceof URLSearchParams))
    .map(([, config]: [string, GetConfig]) => String((config?.params as Record<string, unknown>).status))
}

/** Devuelve la tarjeta (contenedor) que corresponde a una etiqueta de metrica.
 * Las tarjetas con destino son un <a> (5.1 del design); las que no lo tienen
 * (agentes, infraestructura) siguen siendo un <div> — `closest` se detiene
 * en la que sea la más cercana de las dos. */
function statCard(label: string): HTMLElement {
  const labelNode = screen.getByText(label)
  const card = labelNode.closest('div, a')
  if (!card) throw new Error(`La etiqueta "${label}" no esta dentro de una tarjeta`)
  return card as HTMLElement
}

describe('Dashboard — US-04: metricas generales', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('carga las metricas al entrar al dashboard, sin interaccion del usuario', async () => {
    mockBackend()

    renderWithProviders(<Dashboard />)

    // Estado de carga visible antes de que resuelvan las requests.
    expect(screen.getByText(/cargando dashboard/i)).toBeInTheDocument()

    await screen.findByRole('heading', { name: /eventos por estado/i })

    expect(screen.queryByText(/cargando dashboard/i)).not.toBeInTheDocument()
    expect(queriedEventStatuses().length).toBeGreaterThan(0)
    expect(apiGet).toHaveBeenCalledWith('/agents')
    expect(apiGet).toHaveBeenCalledWith('/health/components')
  })

  it('presenta cada metrica como un indicador numerico junto a su etiqueta', async () => {
    mockBackend()

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    // C1/RN-71: la etiqueta ES el valor canónico (5.5) — ver también la
    // cobertura explícita del léxico en "ninguna etiqueta ... difiere" más abajo.
    expect(within(statCard('approved')).getByText('12')).toBeInTheDocument()
    expect(within(statCard('rejected')).getByText('3')).toBeInTheDocument()
    expect(within(statCard('auto_restored')).getByText('2')).toBeInTheDocument()
    expect(within(statCard('quarantined')).getByText('1')).toBeInTheDocument()
    expect(within(statCard('alert_only')).getByText('4')).toBeInTheDocument()
  })

  it('consulta al backend usando el lexico canonico en minusculas snake_case (C1)', async () => {
    mockBackend()

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    const queried = queriedEventStatuses()
    expect(queried.length).toBeGreaterThan(0)
    for (const status of queried) {
      expect(status).toMatch(/^[a-z]+(_[a-z]+)*$/)
      expect(CANONICAL_EVENT_STATUSES).toContain(status as EventStatus)
    }
  })

  // US-04 exige los 7 estados canonicos (RN-71). Este test detecto que el
  // dashboard contaba solo 6: 'superseded' faltaba tanto en EVENT_STATUSES
  // (Dashboard.tsx) como en la lista `statuses` (api/dashboard.ts), asi que los
  // eventos superseded no aparecian en ningun contador. Corregido en ambas listas.
  it('muestra un contador para cada uno de los 7 estados canonicos, incluido superseded', async () => {
    mockBackend()

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    expect(queriedEventStatuses().sort()).toEqual([...CANONICAL_EVENT_STATUSES].sort())
    expect(within(statCard('superseded')).getByText('5')).toBeInTheDocument()
  })

  it('ninguna etiqueta de estado de evento difiere de su valor canónico (C1/RN-71)', async () => {
    mockBackend()

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    // Recorre los siete estados en vez de aserciones sueltas, para que un
    // estado nuevo entre solo en la cobertura (8.5). La etiqueta ES el
    // valor canónico: si alguna pantalla usara un label distinto
    // (`Auto-restored` en vez de `auto_restored`), este `getByText` fallaría.
    for (const status of CANONICAL_EVENT_STATUSES) {
      expect(statCard(status)).toBeInTheDocument()
    }
  })
})

describe('Dashboard — US-05: estado general del sistema', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('indica cuantos eventos pending hay sin resolver', async () => {
    mockBackend({ eventCounts: { pending: 7 } })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    expect(within(statCard('Pending (todos)')).getByText('7')).toBeInTheDocument()
  })

  it('muestra el estado de conectividad de los agentes registrados', async () => {
    // 2 online, 1 offline, 1 draining, 1 dead.
    mockBackend({ agents: ['online', 'online', 'offline', 'draining', 'dead'] })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /^agentes$/i })

    expect(within(statCard('Online')).getByText('2')).toBeInTheDocument()
    expect(within(statCard('Offline')).getByText('1')).toBeInTheDocument()
    expect(within(statCard('Draining')).getByText('1')).toBeInTheDocument()
    expect(within(statCard('Dead')).getByText('1')).toBeInTheDocument()
  })

  it('destaca visualmente los pending critical/high cuando existen', async () => {
    mockBackend({ pendingCriticalHigh: 3 })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    const critical = statCard('Pending critical + high')
    const plain = statCard('Pending (todos)')

    expect(within(critical).getByText('3')).toBeInTheDocument()
    // El realce es puramente visual: la tarjeta se diferencia del resto.
    expect(critical.className).not.toBe(plain.className)
    expect(critical.className).toMatch(/red/)
  })

  it('la tarjeta de pending critical/high enlaza a la lista prefiltrada con los dos severity presentes (8.4)', async () => {
    mockBackend({ pendingCriticalHigh: 2 })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    const card = statCard('Pending critical + high')
    const href = card.getAttribute('href')
    expect(href).toBeTruthy()

    const [path, query] = href!.split('?')
    expect(path).toBe('/events')

    // Destino parseado como URLSearchParams, no la cadena literal, para que
    // el orden de los parámetros no vuelva frágil al test — pero se afirma
    // explícitamente que `getAll('severity')` tiene longitud 2: un href con
    // un solo `severity` es el error plausible acá y tiene que fallar.
    const sp = new URLSearchParams(query)
    expect(sp.get('status')).toBe('pending')
    expect(sp.getAll('severity')).toHaveLength(2)
    expect(sp.getAll('severity').sort()).toEqual(['critical', 'high'])
  })

  it('no destaca la tarjeta de pending critical/high cuando no hay ninguno', async () => {
    mockBackend({ pendingCriticalHigh: 0 })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /eventos por estado/i })

    const critical = statCard('Pending critical + high')
    const plain = statCard('Pending (todos)')

    expect(within(critical).getByText('0')).toBeInTheDocument()
    expect(critical.className).toBe(plain.className)
  })

  it('muestra el estado de la infraestructura monitoreada', async () => {
    mockBackend({ health: { postgres: 'ok', valkey: 'down', n8n: 'ok', agents: 'degraded' } })

    renderWithProviders(<Dashboard />)
    await screen.findByRole('heading', { name: /infraestructura/i })

    expect(within(statCard('valkey')).getByText('down')).toBeInTheDocument()
    expect(within(statCard('agents')).getByText('degraded')).toBeInTheDocument()
    expect(within(statCard('postgres')).getByText('ok')).toBeInTheDocument()
  })
})
