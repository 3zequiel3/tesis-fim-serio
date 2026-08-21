import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AgentCard } from './AgentCard'
import type { Agent } from '@/api/agents'

// D39/RN-133 (frontend-agents spec): AgentCard es el síntoma más visible del
// defecto original — `Date.now() - d.getTime()` sobre un `last_heartbeat`
// sin desfase se leía como hora local y un agente recién latido daba un
// transcurrido NEGATIVO. Estos tests afirman la propiedad que el defecto
// vuelve falsa, no solo que el componente renderiza sin explotar.

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    agent_id: 'agent-tz-test',
    status: 'online',
    watch_paths: ['/etc'],
    queue_pressure: 0.1,
    last_heartbeat: null,
    ruleset_version_applied: 3,
    ...overrides,
  }
}

const noop = () => undefined

describe('AgentCard — transcurrido desde el último latido (8.4)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('un latido de hace pocos segundos produce un transcurrido positivo y pequeño', () => {
    const now = new Date('2026-08-20T19:56:04.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)

    const lastHeartbeat = new Date(now.getTime() - 5_000).toISOString() // 5s atrás
    renderWithProviders(
      <AgentCard agent={makeAgent({ last_heartbeat: lastHeartbeat })} onConfigSave={noop} onRescan={noop} />
    )

    const seen = screen.getByText(/^Visto/)
    expect(seen.textContent).toMatch(/hace 5 segundos/)
    expect(seen.textContent).not.toMatch(/-\d/) // nunca un transcurrido negativo
  })

  it('un agente que nunca latió muestra "nunca", no un transcurrido calculado', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ last_heartbeat: null })} onConfigSave={noop} onRescan={noop} />
    )
    const seen = screen.getByText(/^Visto/)
    expect(seen.textContent).toMatch(/Visto nunca/)
  })

  it('un heartbeat futuro (reloj del agente desincronizado) se rotula, no se resta en negativo', () => {
    const now = new Date('2026-08-20T19:56:00.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)

    const futureHeartbeat = new Date(now.getTime() + 10 * 60_000).toISOString() // 10 min adelantado
    renderWithProviders(
      <AgentCard agent={makeAgent({ last_heartbeat: futureHeartbeat })} onConfigSave={noop} onRescan={noop} />
    )

    const seen = screen.getByText(/^Visto/)
    expect(seen.textContent).toMatch(/dentro de/)
    expect(seen.textContent).not.toMatch(/-\d/)
  })
})

describe('AgentCard — invariancia de zona del transcurrido (8.5)', () => {
  const originalTz = process.env.TZ

  afterEach(() => {
    process.env.TZ = originalTz
    vi.useRealTimers()
  })

  it('el mismo last_heartbeat produce el mismo transcurrido bajo dos zonas de visor distintas', () => {
    const now = new Date('2026-08-20T19:56:04.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    const lastHeartbeat = new Date(now.getTime() - 90_000).toISOString() // 90s atrás

    process.env.TZ = 'America/Argentina/Buenos_Aires'
    const ar = renderWithProviders(
      <AgentCard agent={makeAgent({ last_heartbeat: lastHeartbeat })} onConfigSave={noop} onRescan={noop} />
    )
    const arText = screen.getByText(/^Visto/).textContent
    ar.unmount()

    process.env.TZ = 'UTC'
    renderWithProviders(
      <AgentCard agent={makeAgent({ last_heartbeat: lastHeartbeat })} onConfigSave={noop} onRescan={noop} />
    )
    const utcText = screen.getByText(/^Visto/).textContent

    // El transcurrido ("hace 1 minuto"/"hace 90 segundos") es igual — es
    // propiedad de los instantes, no de la zona de visualización.
    expect(arText?.match(/hace [\d.,]+ \w+/)?.[0]).toBe(utcText?.match(/hace [\d.,]+ \w+/)?.[0])
  })
})
