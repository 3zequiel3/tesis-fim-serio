import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

// ── US-21: queue_size local mostrado ──────────────────────────────────────────

describe('AgentCard — queue_size local (US-21)', () => {
  it('muestra el queue_size reportado por el agente', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ queue_size: 12 })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.getByText(/12/)).toBeInTheDocument()
  })

  it('un agente que nunca reportó queue_size lo muestra como desconocido, no como 0', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ queue_size: null })} onConfigSave={noop} onRescan={noop} />
    )
    // D37/RN-131 ya estableció este criterio para discarded_events — mismo
    // principio para queue_size: null != 0.
    expect(screen.queryByText(/Cola local: 0/)).not.toBeInTheDocument()
  })
})

// ── US-30: indicador "Drenando N eventos" + tooltip canónico ────────────────

describe('AgentCard — indicador de drenaje graceful (US-30)', () => {
  it('un agente draining muestra "Drenando N eventos" con el queue_size actual', () => {
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ status: 'draining', queue_size: 5 })}
        onConfigSave={noop}
        onRescan={noop}
      />
    )
    expect(screen.getByText(/Drenando 5 eventos/)).toBeInTheDocument()
  })

  it('un agente online no muestra el indicador de drenaje', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ status: 'online' })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.queryByText(/Drenando/)).not.toBeInTheDocument()
  })

  it('el botón de rescan tiene el tooltip canónico exacto durante el drenaje', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ status: 'draining' })} onConfigSave={noop} onRescan={noop} />
    )
    const rescanButton = screen.getByRole('button', { name: /rescan/i })
    expect(rescanButton).toBeDisabled()
    expect(rescanButton).toHaveAttribute('title', 'No disponible durante shutdown graceful')
  })

  it('el botón de editar paths (update config) tiene el mismo tooltip canónico durante el drenaje', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ status: 'draining' })} onConfigSave={noop} onRescan={noop} />
    )
    const editButton = screen.getByRole('button', { name: /editar/i })
    expect(editButton).toBeDisabled()
    expect(editButton).toHaveAttribute('title', 'No disponible durante shutdown graceful')
  })
})

// ── US-21 (W3): banner de queue_pressure > 80% ───────────────────────────────

describe('AgentCard — banner de presión de cola alta (US-21/W3)', () => {
  it('queue_pressure > 80% muestra un banner de alerta específico del agente', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ queue_pressure: 0.85 })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('queue_pressure <= 80% no muestra el banner', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ queue_pressure: 0.5 })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

// ── US-22: selección de paths específicos para el rescan ────────────────────

describe('AgentCard — selección de paths para rescan (US-22)', () => {
  it('con múltiples watch_paths, permite deseleccionar uno y sólo pasa los seleccionados a onRescan', async () => {
    const user = userEvent.setup()
    const onRescan = vi.fn()
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ watch_paths: ['/etc', '/var/lib/fim'] })}
        onConfigSave={noop}
        onRescan={onRescan}
      />
    )

    // Ambos paths están seleccionados por defecto.
    const varCheckbox = screen.getByRole('checkbox', { name: /\/var\/lib\/fim/ })
    await user.click(varCheckbox)

    await user.click(screen.getByRole('button', { name: /rescan/i }))

    expect(onRescan).toHaveBeenCalledWith('agent-tz-test', ['/etc'])
  })

  it('sin deseleccionar nada, pasa todos los watch_paths', async () => {
    const user = userEvent.setup()
    const onRescan = vi.fn()
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ watch_paths: ['/etc', '/var/lib/fim'] })}
        onConfigSave={noop}
        onRescan={onRescan}
      />
    )

    await user.click(screen.getByRole('button', { name: /rescan/i }))

    expect(onRescan).toHaveBeenCalledWith('agent-tz-test', ['/etc', '/var/lib/fim'])
  })
})
