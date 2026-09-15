import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, within } from '@testing-library/react'
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

// ── US-24: gestión de paths monitoreados desde el frontend ──────────────────
//
// C1: lista de paths actualmente monitoreados por agente.
// C2: opción de agregar un nuevo path.
// C3: opción de quitar un path existente.
// C11: si el agente está `draining`, los botones de guardar configuración
// quedan deshabilitados (ver US-30). Las criterios de infraestructura
// (persistencia PostgreSQL, comando update_config firmado HMAC, reload en
// caliente del agente, baseline scan automático, event_ack, audit_log) ya
// fueron demostrados por el lab fanotify privilegiado de la lane L7 — fuera
// de alcance de este archivo, que cubre solo la UI.

describe('AgentCard — lista de paths monitoreados (US-24/C1)', () => {
  it('muestra todos los watch_paths actualmente monitoreados por el agente', () => {
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ watch_paths: ['/etc', '/var/lib/fim', '/home/user'] })}
        onConfigSave={noop}
        onRescan={noop}
      />
    )

    // Con >1 watch_paths también se renderiza la selección de re-escaneo
    // (US-22), que repite los mismos paths como <label> — se acota la
    // aserción a la sección "Watch paths" propiamente dicha.
    const watchPathsSection = screen.getByText('Watch paths').closest('div')!.parentElement!
    expect(within(watchPathsSection).getByText('/etc')).toBeInTheDocument()
    expect(within(watchPathsSection).getByText('/var/lib/fim')).toBeInTheDocument()
    expect(within(watchPathsSection).getByText('/home/user')).toBeInTheDocument()
  })
})

describe('AgentCard — agregar un nuevo path (US-24/C2)', () => {
  it('agrega el path escrito al listado y lo envía en onConfigSave al guardar', async () => {
    const user = userEvent.setup()
    const onConfigSave = vi.fn()
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ watch_paths: ['/etc'] })}
        onConfigSave={onConfigSave}
        onRescan={noop}
      />
    )

    await user.click(screen.getByRole('button', { name: /editar/i }))
    await user.type(screen.getByPlaceholderText('/ruta/nueva'), '/var/lib/fim')
    await user.click(screen.getByRole('button', { name: /^agregar$/i }))

    expect(screen.getByText('/var/lib/fim')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /guardar paths/i }))

    expect(onConfigSave).toHaveBeenCalledWith('agent-tz-test', ['/etc', '/var/lib/fim'])
  })
})

describe('AgentCard — quitar un path existente (US-24/C3)', () => {
  it('quita el path seleccionado del listado y lo envía sin él en onConfigSave al guardar', async () => {
    const user = userEvent.setup()
    const onConfigSave = vi.fn()
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ watch_paths: ['/etc', '/var/lib/fim'] })}
        onConfigSave={onConfigSave}
        onRescan={noop}
      />
    )

    await user.click(screen.getByRole('button', { name: /editar/i }))

    // El path aparece dos veces mientras se edita: en el listado editable
    // (con "Quitar") y en la selección de paths a re-escanear (US-22) — el
    // primero en orden de DOM es el editable.
    const editingList = screen.getAllByText('/var/lib/fim')[0].closest('li')!
    await user.click(within(editingList).getByRole('button', { name: /quitar/i }))

    expect(
      screen.queryByText('/var/lib/fim', { selector: 'span.font-mono' })
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /guardar paths/i }))

    expect(onConfigSave).toHaveBeenCalledWith('agent-tz-test', ['/etc'])
  })
})

describe('AgentCard — botón de guardar deshabilitado durante drenaje (US-24/C11, ver US-30)', () => {
  it('el botón "Guardar paths" está deshabilitado con el tooltip canónico cuando el agente está draining', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(
      <AgentCard
        agent={makeAgent({ status: 'online', watch_paths: ['/etc'] })}
        onConfigSave={noop}
        onRescan={noop}
      />
    )

    // Se entra en modo edición mientras el agente todavía está online.
    await user.click(screen.getByRole('button', { name: /editar/i }))
    expect(screen.getByRole('button', { name: /guardar paths/i })).toBeEnabled()

    // El agente pasa a draining (p. ej. por refetch de polling) mientras la
    // edición ya estaba abierta — el botón de guardar debe deshabilitarse
    // igual, no solo el de "Editar" al entrar.
    rerender(
      <AgentCard
        agent={makeAgent({ status: 'draining', watch_paths: ['/etc'] })}
        onConfigSave={noop}
        onRescan={noop}
      />
    )

    const saveButton = screen.getByRole('button', { name: /guardar paths/i })
    expect(saveButton).toBeDisabled()
    expect(saveButton).toHaveAttribute('title', 'No disponible durante shutdown graceful')
  })

  it('un agente que ya está draining al abrir la tarjeta no puede llegar a guardar (Editar deshabilitado)', () => {
    renderWithProviders(
      <AgentCard
        agent={makeAgent({ status: 'draining', watch_paths: ['/etc'] })}
        onConfigSave={noop}
        onRescan={noop}
      />
    )

    const editButton = screen.getByRole('button', { name: /editar/i })
    expect(editButton).toBeDisabled()
    expect(screen.queryByRole('button', { name: /guardar paths/i })).not.toBeInTheDocument()
  })
})

// ── US-21: ruleset_version aplicado y realce de agentes no-ok ─────────────────
describe('AgentCard — US-21 ruleset aplicado y realce de estados no-ok', () => {
  it('muestra el ruleset_version aplicado por el agente', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ ruleset_version_applied: 7 })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.getByText(/ruleset v7/)).toBeTruthy()
  })

  it('no inventa un ruleset cuando el agente todavía no aplicó ninguno', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ ruleset_version_applied: undefined })} onConfigSave={noop} onRescan={noop} />
    )
    expect(screen.queryByText(/ruleset v/)).toBeNull()
  })

  it.each([
    ['dead', 'bg-red-800'],
    ['draining', 'bg-yellow-700'],
    ['offline', 'bg-gray-600'],
  ] as const)('realza el estado no-ok %s con su color propio', (status, colorClass) => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ status })} onConfigSave={noop} onRescan={noop} />
    )
    const badge = screen.getByText(status, { selector: 'span' })
    expect(badge.className).toContain(colorClass)
  })

  it('un agente online no usa los colores de alerta', () => {
    renderWithProviders(
      <AgentCard agent={makeAgent({ status: 'online' })} onConfigSave={noop} onRescan={noop} />
    )
    const badge = screen.getByText('online', { selector: 'span' })
    expect(badge.className).not.toContain('bg-red-800')
    expect(badge.className).not.toContain('bg-yellow-700')
  })
})

