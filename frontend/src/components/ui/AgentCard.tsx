import { useState } from 'react'
import { Hourglass } from 'lucide-react'
import { Can } from '@/components/ui/Can'
import { Button } from '@/components/ui/Button'
import { inputClassName } from '@/components/ui/Field'
import {
  EMPTY_LIST_MESSAGE,
  canonicalWatchPath,
  describeWatchPath,
  validateWatchPaths,
} from '@/utils/watchPaths'
import type { Agent } from '@/api/agents'
import { getWatchPathStatusMeta } from '@/utils/watchPathStatus'
import { getDiscardedEventsMeta } from '@/utils/discardedEvents'
import { getOutOfScopeDropsMeta } from '@/utils/outOfScopeDrops'
import { formatAbsolute, formatRelative } from '@/utils/timeDisplay'
import { getAgentStatusMeta } from '@/utils/agentStatus'
import { CanonicalLabel } from '@/components/ui/CanonicalLabel'

/** A backend rejection of the watch_paths save, shown next to the entry it names (D91/RN-185). */
export interface ConfigSaveError {
  message: string
  /** Index into the list that was sent. */
  index?: number
}

interface AgentCardProps {
  agent: Agent
  /**
   * Resolves `false` when the save failed (the editor then stays open with the
   * error); anything else closes the editor.
   */
  onConfigSave: (id: string, paths: string[]) => void | boolean | Promise<boolean | void>
  configError?: ConfigSaveError | null
  // US-22: `rescanPaths` son los paths seleccionados para el rescan — todos
  // los watch_paths por defecto (comportamiento previo).
  onRescan: (id: string, rescanPaths: string[]) => void
  isSavingConfig?: boolean
  isRescanning?: boolean
}

// US-30/RN-93 (W17): tooltip canónico exacto para cualquier acción
// deshabilitada mientras el agente está en drenaje graceful.
const DRAINING_TOOLTIP = 'No disponible durante shutdown graceful'

// D36/RN-130 (C41): indicador por path de que la remediación automática no
// puede correr ahí (path monitoreado, no remediable) o de que el path no
// existe. Se omite por completo cuando el agente no reportó mapa (agente
// viejo, o sin heartbeat aún) o cuando el path es escribible — ver
// getWatchPathStatusMeta. Visualmente distinto del badge de status del
// agente (getAgentStatusMeta): esto es una degradación parcial, no una falla.
function WatchPathStatusIndicator({ status }: { status: string | undefined }) {
  const meta = getWatchPathStatusMeta(status)
  if (!meta) return null
  return (
    <span
      title={meta.title}
      className={`shrink-0 rounded-control px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap ${meta.className}`}
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
      className={`shrink-0 rounded-control px-1.5 py-0.5 text-xs font-semibold tabular-nums whitespace-nowrap ${meta.className}`}
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
      className={`shrink-0 rounded-control px-1.5 py-0.5 text-xs font-semibold tabular-nums whitespace-nowrap ${meta.className}`}
    >
      Fuera de alcance: {meta.label}
    </span>
  )
}

function WatchPathsEditor({
  agent,
  isSaving,
  isDraining,
  configError,
  onSave,
  onClose,
}: {
  agent: Agent
  isSaving?: boolean
  isDraining: boolean
  configError?: ConfigSaveError | null
  onSave: AgentCardProps['onConfigSave']
  onClose: () => void
}) {
  const [paths, setPaths] = useState<string[]>(agent.watch_paths)
  const [newPath, setNewPath] = useState('')
  const [typedError, setTypedError] = useState<string | null>(null)
  const [listIssue, setListIssue] = useState<{ message: string; index?: number } | null>(null)

  const typed = newPath.trim()
  // D12b: the editor never sends an empty list.
  const wouldBeEmpty = paths.length === 0 && typed === ''

  function handleAddPath() {
    if (!typed) return
    const problem = describeWatchPath(typed)
    if (problem) {
      setTypedError(problem)
      return
    }
    if (paths.some((p) => canonicalWatchPath(p) === canonicalWatchPath(typed))) {
      setTypedError('La ruta está repetida (con o sin la barra final).')
      return
    }
    setPaths([...paths, typed])
    setNewPath('')
    setTypedError(null)
    setListIssue(null)
  }

  async function handleSave() {
    setTypedError(null)
    setListIssue(null)
    // A path typed but not added with «Agregar» is part of what the admin sees as the list.
    let next = paths
    if (typed) {
      const problem = describeWatchPath(typed)
      if (problem) {
        setTypedError(problem)
        return
      }
      next = [...paths, typed]
    }
    const issue = validateWatchPaths(next)
    if (issue) {
      if (issue.index != null && issue.index >= paths.length) setTypedError(issue.message)
      else setListIssue(issue)
      return
    }
    const result = await onSave(agent.agent_id, next)
    if (result !== false) onClose()
  }

  function handleRemovePath(path: string) {
    setPaths(paths.filter((p) => p !== path))
    setListIssue(null)
  }

  const serverIndex = configError?.index

  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {paths.map((p, i) => {
          const inline =
            listIssue?.index === i ? listIssue.message : serverIndex === i ? configError?.message : null
          return (
            <li key={p} className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="flex-1 font-mono text-xs [overflow-wrap:anywhere]">{p}</span>
                <Button variant="ghost" size="sm" onClick={() => handleRemovePath(p)}>
                  Quitar
                </Button>
              </div>
              {inline && <p role="alert" className="text-xs text-danger-fg">{inline}</p>}
            </li>
          )
        })}
      </ul>
      <div className="flex gap-2">
        <input
          type="text"
          value={newPath}
          onChange={(e) => {
            setNewPath(e.target.value)
            setTypedError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleAddPath()
            }
          }}
          placeholder="/ruta/nueva"
          aria-label="Ruta nueva"
          aria-invalid={typedError ? 'true' : undefined}
          className={`${inputClassName} !py-1 font-mono text-xs`}
        />
        <Button size="sm" onClick={handleAddPath}>
          Agregar
        </Button>
      </div>
      {typedError && <p role="alert" className="text-xs text-danger-fg">{typedError}</p>}
      {wouldBeEmpty && <p role="alert" className="text-xs text-warning-fg">{EMPTY_LIST_MESSAGE}</p>}
      {configError && (serverIndex == null || serverIndex >= paths.length) && (
        <p role="alert" className="text-xs text-danger-fg">{configError.message}</p>
      )}
      {listIssue && listIssue.index == null && (
        <p role="alert" className="text-xs text-danger-fg">{listIssue.message}</p>
      )}
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          onClick={() => void handleSave()}
          disabled={isSaving || isDraining || wouldBeEmpty}
          title={isDraining ? DRAINING_TOOLTIP : undefined}
        >
          {isSaving ? 'Guardando...' : 'Guardar rutas'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
        >
          Cancelar
        </Button>
      </div>
    </div>
  )
}

// M4: this component is remounted (key = the watch paths) whenever the agent's
// paths change, so the selection is always rebuilt from the current list and
// never keeps a path that no longer exists.
function RescanSection({
  agent,
  isDraining,
  isRescanning,
  onRescan,
}: {
  agent: Agent
  isDraining: boolean
  isRescanning?: boolean
  onRescan: AgentCardProps['onRescan']
}) {
  const [rescanPaths, setRescanPaths] = useState<string[]>(agent.watch_paths)

  function toggleRescanPath(path: string) {
    setRescanPaths((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]))
  }

  const noneSelected = agent.watch_paths.length > 0 && rescanPaths.length === 0

  return (
    <>
      {/* US-22: selección de paths específicos para el rescan. Sólo tiene
          sentido elegir si hay más de un path configurado. */}
      {agent.watch_paths.length > 1 && (
        <div>
          <span className="text-xs font-semibold text-text-muted">Rutas a re-escanear</span>
          <ul className="mt-1 space-y-0.5">
            {agent.watch_paths.map((p) => (
              <li key={p} className="flex items-center gap-2">
                <input
                  id={`rescan-path-${agent.agent_id}-${p}`}
                  type="checkbox"
                  checked={rescanPaths.includes(p)}
                  onChange={() => toggleRescanPath(p)}
                  disabled={isDraining}
                  aria-label={p}
                  className="size-4 shrink-0 accent-accent"
                />
                <label
                  htmlFor={`rescan-path-${agent.agent_id}-${p}`}
                  className="font-mono text-xs text-text-muted [overflow-wrap:anywhere]"
                >
                  {p}
                </label>
              </li>
            ))}
          </ul>
          {noneSelected && (
            <p className="mt-1 text-xs text-warning-fg">Elegí al menos una ruta para re-escanear.</p>
          )}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <Button
          className="flex-1"
          onClick={() => onRescan(agent.agent_id, rescanPaths)}
          disabled={isDraining || isRescanning || noneSelected}
          title={isDraining ? DRAINING_TOOLTIP : undefined}
        >
          {isRescanning ? 'Volviendo a escanear…' : 'Volver a escanear'}
        </Button>
      </div>
    </>
  )
}

export function AgentCard({
  agent,
  onConfigSave,
  configError,
  onRescan,
  isSavingConfig,
  isRescanning,
}: AgentCardProps) {
  const isDraining = agent.status === 'draining'
  const [editingPaths, setEditingPaths] = useState(false)

  const pressurePct = Math.round((agent.queue_pressure ?? 0) * 100)
  // W3/RN-84, D72/RN-166: banner de alerta específico del agente cuando la
  // cola local supera el 80% de presión. El umbral se calcula en el agente,
  // no acá: el banner depende únicamente del flag `queue_pressure_high`. Sin
  // respaldo por umbral en el cliente para agentes que no envían la clave
  // (D72/RN-166) — reintroduciría la divergencia que esta decisión cierra.
  const showQueuePressureBanner = agent.queue_pressure_high === true

  return (
    <div
      className={`space-y-3 rounded-panel border bg-surface-raised p-4 ${
        agent.status === 'dead' || agent.status === 'revoked'
          ? 'border-danger-line border-l-4'
          : 'border-line'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        {/* No hay `hostname` en el backend (RN-71 / C35 FIX-03) — agent_id es la identidad, como en core/health.py:97 */}
        <p className="font-mono font-semibold text-text [overflow-wrap:anywhere]">{agent.agent_id}</p>
        <CanonicalLabel
          name={getAgentStatusMeta(agent.status).label}
          value={agent.status}
          className={`shrink-0 rounded-control px-2 py-0.5 text-xs font-semibold ${getAgentStatusMeta(agent.status).toneClass}`}
        />
      </div>

      {/* US-30 (RN-93/W17): indicador distintivo de drenaje graceful. N desconocido
          se muestra como 0 en vez de omitir el indicador. */}
      {isDraining && (
        <div className="flex items-center gap-1.5 rounded-control border border-warning-line bg-warning-bg px-2 py-1 text-xs text-warning-fg">
          <Hourglass aria-hidden="true" size={14} />
          <span>Drenando {agent.queue_size ?? 0} eventos</span>
        </div>
      )}

      {/* Queue pressure */}
      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-1">
          <span className="text-xs text-text-muted">Presión de cola</span>
          <span className="flex flex-wrap items-center gap-2 text-xs">
            <span className="tabular-nums text-text">{pressurePct}%</span>
            <DiscardedEventsIndicator count={agent.discarded_events} />
            <OutOfScopeDropsIndicator count={agent.out_of_scope_drops} />
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full border border-line bg-surface">
          <div
            className={`h-full rounded-full transition-all ${
              pressurePct > 80 ? 'bg-status-rejected' : pressurePct > 50 ? 'bg-status-pending' : 'bg-status-approved'
            }`}
            style={{ width: `${pressurePct}%` }}
          />
        </div>
        {/* W3/RN-84: banner específico del agente cuando la cola local supera el 80%. */}
        {showQueuePressureBanner && (
          <div
            role="alert"
            className="mt-1.5 rounded-control border border-danger-line bg-danger-bg px-2 py-1 text-xs text-danger-fg"
          >
            Cola local por encima del 80% — riesgo de pérdida de eventos.
          </div>
        )}
        {/* US-21: cola local reportada por el agente. null/undefined = nunca reportó heartbeat. */}
        <p className="mt-1 text-xs text-text-muted">Cola local: {agent.queue_size ?? '—'} eventos</p>
      </div>

      {/* Last seen — D39/RN-133: forma relativa + absoluta con zona visible. El
          transcurrido nunca es negativo: un heartbeat futuro se rotula como tal. */}
      <p className="text-xs text-text-muted" title={formatAbsolute(agent.last_heartbeat, { nullLabel: 'nunca' })}>
        Visto {formatRelative(agent.last_heartbeat, { nullLabel: 'nunca' })}
        {agent.last_heartbeat && <span className="ml-2">({formatAbsolute(agent.last_heartbeat)})</span>}
        {agent.ruleset_version_applied != null && (
          <span className="ml-2">· ruleset v{agent.ruleset_version_applied}</span>
        )}
      </p>

      {/* Watch paths */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold text-text-muted">Rutas vigiladas</span>
          {!editingPaths && (
            <Can>
              <button
                onClick={() => setEditingPaths(true)}
                disabled={isDraining}
                title={isDraining ? DRAINING_TOOLTIP : undefined}
                className="text-xs font-semibold text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-40"
              >
                Editar
              </button>
            </Can>
          )}
        </div>

        {editingPaths ? (
          <WatchPathsEditor
            agent={agent}
            isSaving={isSavingConfig}
            isDraining={isDraining}
            configError={configError}
            onSave={onConfigSave}
            onClose={() => setEditingPaths(false)}
          />
        ) : (
          <ul className="space-y-0.5">
            {agent.watch_paths.length === 0 ? (
              <li className="text-xs italic text-text-muted">Sin rutas configuradas</li>
            ) : (
              agent.watch_paths.map((p) => (
                <li key={p} className="flex min-w-0 items-center gap-2">
                  <span className="min-w-0 flex-1 font-mono text-xs text-text [overflow-wrap:anywhere]">{p}</span>
                  <WatchPathStatusIndicator status={agent.watch_path_status?.[p]} />
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      <Can>
        <RescanSection
          key={agent.watch_paths.join('\n')}
          agent={agent}
          isDraining={isDraining}
          isRescanning={isRescanning}
          onRescan={onRescan}
        />
      </Can>
    </div>
  )
}
