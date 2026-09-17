import { useState } from 'react'
import type { Agent } from '@/api/agents'
import { getWatchPathStatusMeta } from '@/utils/watchPathStatus'
import { getDiscardedEventsMeta } from '@/utils/discardedEvents'
import { getOutOfScopeDropsMeta } from '@/utils/outOfScopeDrops'
import { formatAbsolute, formatRelative } from '@/utils/timeDisplay'

interface AgentCardProps {
  agent: Agent
  onConfigSave: (id: string, paths: string[]) => void
  // US-22: `rescanPaths` son los paths seleccionados para el rescan — todos
  // los watch_paths por defecto (comportamiento previo).
  onRescan: (id: string, rescanPaths: string[]) => void
  isSavingConfig?: boolean
  isRescanning?: boolean
}

// US-30/RN-93 (W17): tooltip canónico exacto para cualquier acción
// deshabilitada mientras el agente está en drenaje graceful.
const DRAINING_TOOLTIP = 'No disponible durante shutdown graceful'

const STATUS_STYLES: Record<Agent['status'], string> = {
  online: 'bg-green-700 text-green-200',
  offline: 'bg-gray-600 text-gray-300',
  draining: 'bg-yellow-700 text-yellow-200',
  dead: 'bg-red-800 text-red-200',
  revoked: 'bg-red-900 text-red-300',
}

// D36/RN-130 (C41): indicador por path de que la remediación automática no
// puede correr ahí (path monitoreado, no remediable) o de que el path no
// existe. Se omite por completo cuando el agente no reportó mapa (agente
// viejo, o sin heartbeat aún) o cuando el path es escribible — ver
// getWatchPathStatusMeta. Visualmente distinto del badge de status del
// agente (STATUS_STYLES): esto es una degradación parcial, no una falla.
function WatchPathStatusIndicator({ status }: { status: string | undefined }) {
  const meta = getWatchPathStatusMeta(status)
  if (!meta) return null
  return (
    <span
      title={meta.title}
      className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${meta.className}`}
    >
      {meta.label}
    </span>
  )
}

// D37/RN-131 (C42): contador de eventos descartados localmente por el
// transporte del agente, mostrado junto a la presión de cola que ya expone
// esta tarjeta. Un conteo positivo es una detección perdida — se resalta
// como anomalía. "Nunca reportó" se distingue explícitamente de "cero" (ver
// getDiscardedEventsMeta): mostrar "0" cuando en realidad no sabemos sería
// exactamente la confusión que este indicador existe para prevenir.
function DiscardedEventsIndicator({ count }: { count: number | null | undefined }) {
  const meta = getDiscardedEventsMeta(count)
  return (
    <span
      title={meta.title}
      className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium tabular-nums whitespace-nowrap ${meta.className}`}
    >
      Descartes: {meta.label}
    </span>
  )
}

// D69/RN-163: contador de eventos descartados por caer fuera de los
// watch_paths, mostrado junto a DiscardedEventsIndicator a propósito: los
// dos están al lado y DEBEN verse distintos. Acá un positivo es esperado
// (evidencia de que el filtro de scope funciona), no una detección perdida
// como en discarded_events — por eso getOutOfScopeDropsMeta nunca usa la
// paleta de alarma, ni siquiera en el estado positivo.
function OutOfScopeDropsIndicator({ count }: { count: number | null | undefined }) {
  const meta = getOutOfScopeDropsMeta(count)
  return (
    <span
      title={meta.title}
      className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium tabular-nums whitespace-nowrap ${meta.className}`}
    >
      Fuera de scope: {meta.label}
    </span>
  )
}

export function AgentCard({
  agent,
  onConfigSave,
  onRescan,
  isSavingConfig,
  isRescanning,
}: AgentCardProps) {
  const isDraining = agent.status === 'draining'
  const [editingPaths, setEditingPaths] = useState(false)
  const [paths, setPaths] = useState<string[]>(agent.watch_paths)
  const [newPath, setNewPath] = useState('')
  // US-22: paths seleccionados para el próximo rescan — todos por defecto.
  const [rescanPaths, setRescanPaths] = useState<string[]>(agent.watch_paths)

  const pressurePct = Math.round((agent.queue_pressure ?? 0) * 100)
  // W3/RN-84: banner de alerta específico del agente cuando la cola local
  // supera el 80% de presión.
  const showQueuePressureBanner = pressurePct > 80

  function toggleRescanPath(path: string) {
    setRescanPaths((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    )
  }

  function handleAddPath() {
    const trimmed = newPath.trim()
    if (trimmed && !paths.includes(trimmed)) {
      setPaths([...paths, trimmed])
    }
    setNewPath('')
  }

  function handleRemovePath(path: string) {
    setPaths(paths.filter((p) => p !== path))
  }

  function handleSavePaths() {
    onConfigSave(agent.agent_id, paths)
    setEditingPaths(false)
  }

  function handleCancelEdit() {
    setPaths(agent.watch_paths)
    setEditingPaths(false)
    setNewPath('')
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          {/* No hay `hostname` en el backend (RN-71 / C35 FIX-03) — agent_id es la identidad, como en core/health.py:97 */}
          <p className="text-sm font-semibold text-white font-mono">{agent.agent_id}</p>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[agent.status]}`}
        >
          {agent.status}
        </span>
      </div>

      {/* US-30 (RN-93/W17): indicador distintivo de drenaje graceful — el
          agente sigue publicando su cola local (queue_size) mientras drena;
          se muestra "Drenando N eventos" con un ícono, no solo el badge de
          estado. N desconocido (agente que aún no reportó heartbeat en este
          ciclo) se muestra como 0 en vez de omitir el indicador. */}
      {isDraining && (
        <div className="flex items-center gap-1.5 text-xs text-yellow-300 bg-yellow-900/30 border border-yellow-700 rounded px-2 py-1">
          <span aria-hidden="true">⏳</span>
          <span>Drenando {agent.queue_size ?? 0} eventos</span>
        </div>
      )}

      {/* Queue pressure */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Queue pressure</span>
          <span className="flex items-center gap-2 text-xs">
            <span className="text-gray-300 tabular-nums">{pressurePct}%</span>
            <DiscardedEventsIndicator count={agent.discarded_events} />
            <OutOfScopeDropsIndicator count={agent.out_of_scope_drops} />
          </span>
        </div>
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              pressurePct > 80
                ? 'bg-red-500'
                : pressurePct > 50
                ? 'bg-yellow-500'
                : 'bg-green-500'
            }`}
            style={{ width: `${pressurePct}%` }}
          />
        </div>
        {/* W3/RN-84: banner específico del agente cuando la cola local supera
            el 80% — distinto de la barra de color, que ya existía. */}
        {showQueuePressureBanner && (
          <div
            role="alert"
            className="mt-1.5 text-xs text-red-200 bg-red-900/40 border border-red-700 rounded px-2 py-1"
          >
            Cola local por encima del 80% — riesgo de pérdida de eventos.
          </div>
        )}
        {/* US-21: cola local reportada por el agente (distinto de la presión
            en bytes). null/undefined = el agente nunca reportó heartbeat. */}
        <p className="mt-1 text-[11px] text-gray-500">
          Cola local: {agent.queue_size ?? '—'} eventos
        </p>
      </div>

      {/* Last seen — D39/RN-133: forma relativa + absoluta con zona visible
          (frontend-agents spec). El transcurrido nunca es negativo: un
          heartbeat futuro (reloj del agente desincronizado, RN-90/RN-131)
          se rotula como tal en vez de restar en negativo. */}
      <p className="text-xs text-gray-500" title={formatAbsolute(agent.last_heartbeat, { nullLabel: 'nunca' })}>
        Visto {formatRelative(agent.last_heartbeat, { nullLabel: 'nunca' })}
        {agent.last_heartbeat && (
          <span className="ml-2 text-gray-600">
            ({formatAbsolute(agent.last_heartbeat)})
          </span>
        )}
        {agent.ruleset_version_applied != null && (
          <span className="ml-2">· ruleset v{agent.ruleset_version_applied}</span>
        )}
      </p>

      {/* Watch paths */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Watch paths</span>
          {!editingPaths && (
            <button
              onClick={() => setEditingPaths(true)}
              disabled={isDraining}
              title={isDraining ? DRAINING_TOOLTIP : undefined}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Editar
            </button>
          )}
        </div>

        {editingPaths ? (
          <div className="space-y-2">
            <ul className="space-y-1">
              {paths.map((p) => (
                <li key={p} className="flex items-center gap-2">
                  <span className="flex-1 text-xs font-mono text-gray-300 truncate">{p}</span>
                  <button
                    onClick={() => handleRemovePath(p)}
                    className="text-xs text-red-400 hover:text-red-300 shrink-0"
                  >
                    Quitar
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input
                type="text"
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddPath()}
                placeholder="/ruta/nueva"
                className="flex-1 px-2 py-1 text-xs bg-gray-900 border border-gray-600 rounded text-gray-200 placeholder-gray-600 focus:outline-none focus:border-primary"
              />
              <button
                onClick={handleAddPath}
                className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded"
              >
                Agregar
              </button>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleSavePaths}
                disabled={isSavingConfig || isDraining}
                title={isDraining ? DRAINING_TOOLTIP : undefined}
                className="px-3 py-1 text-xs bg-primary hover:bg-primary-hover text-white rounded disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isSavingConfig ? 'Guardando...' : 'Guardar paths'}
              </button>
              <button
                onClick={handleCancelEdit}
                className="px-3 py-1 text-xs text-gray-400 hover:text-gray-200"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {agent.watch_paths.length === 0 ? (
              <li className="text-xs text-gray-600 italic">Sin paths configurados</li>
            ) : (
              agent.watch_paths.map((p) => (
                <li key={p} className="flex items-center gap-2 min-w-0">
                  <span className="flex-1 text-xs font-mono text-gray-400 truncate">{p}</span>
                  <WatchPathStatusIndicator
                    status={agent.watch_path_status?.[p]}
                  />
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      {/* US-22: selección de paths específicos para el rescan — todos los
          watch_paths seleccionados por defecto (comportamiento previo). Solo
          tiene sentido elegir si hay más de un path configurado. */}
      {agent.watch_paths.length > 1 && (
        <div>
          <span className="text-xs text-gray-400">Paths a re-escanear</span>
          <ul className="space-y-0.5 mt-1">
            {agent.watch_paths.map((p) => (
              <li key={p} className="flex items-center gap-2">
                <input
                  id={`rescan-path-${agent.agent_id}-${p}`}
                  type="checkbox"
                  checked={rescanPaths.includes(p)}
                  onChange={() => toggleRescanPath(p)}
                  disabled={isDraining}
                  aria-label={p}
                  className="shrink-0"
                />
                <label
                  htmlFor={`rescan-path-${agent.agent_id}-${p}`}
                  className="text-xs font-mono text-gray-400 truncate"
                >
                  {p}
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onRescan(agent.agent_id, rescanPaths)}
          disabled={isDraining || isRescanning}
          title={isDraining ? DRAINING_TOOLTIP : undefined}
          className="flex-1 px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded border border-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isRescanning ? 'Rescaneando...' : 'Rescan'}
        </button>
      </div>
    </div>
  )
}
