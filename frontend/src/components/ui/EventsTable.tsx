import { Link } from 'react-router-dom'
import type { EventListItem } from '@/api/events'
import { getAckStatusMeta } from '@/utils/ackStatus'
import { getActionFailedMeta } from '@/utils/actionFailed'
import { formatAbsolute } from '@/utils/timeDisplay'
import { getSeverityMeta } from '@/utils/severity'

interface EventsTableProps {
  items: EventListItem[]
  selected: Set<number>
  onSelectionChange: (selected: Set<number>) => void
}

const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-yellow-900 text-yellow-300',
  approved: 'bg-green-900 text-green-300',
  rejected: 'bg-red-900 text-red-300',
  superseded: 'bg-gray-700 text-gray-400',
  auto_restored: 'bg-blue-900 text-blue-300',
  quarantined: 'bg-orange-900 text-orange-300',
  alert_only: 'bg-purple-900 text-purple-300',
}

/**
 * Etiqueta del proceso causante (US-06), o null cuando los tres campos son
 * null — un evento sin contexto de proceso es un caso normal, no un error
 * de datos, y no se renderiza ni vacío ni con guiones (:3.5).
 */
function processContextLabel(item: EventListItem): string | null {
  if (item.process_pid == null && item.process_uid == null && item.process_exe == null) {
    return null
  }
  const parts: string[] = []
  if (item.process_pid != null) parts.push(`pid ${item.process_pid}`)
  if (item.process_uid != null) parts.push(`uid ${item.process_uid}`)
  const exe = item.process_exe ?? '?'
  return parts.length > 0 ? `${exe} (${parts.join(', ')})` : exe
}

export function EventsTable({ items, selected, onSelectionChange }: EventsTableProps) {
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id))
  const someSelected = items.some((item) => selected.has(item.id))

  function toggleAll() {
    if (allSelected) {
      // Deseleccionar todos los de la página
      const next = new Set(selected)
      items.forEach((item) => next.delete(item.id))
      onSelectionChange(next)
    } else {
      // Seleccionar todos los de la página
      const next = new Set(selected)
      items.forEach((item) => next.add(item.id))
      onSelectionChange(next)
    }
  }

  function toggleRow(id: number) {
    const next = new Set(selected)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    onSelectionChange(next)
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No hay eventos que coincidan con los filtros actuales.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded border border-gray-700">
      <table className="w-full text-sm text-left text-gray-300">
        <thead className="text-xs uppercase text-gray-400 bg-gray-800 border-b border-gray-700">
          <tr>
            <th className="px-3 py-3 w-10">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected && !allSelected
                }}
                onChange={toggleAll}
                aria-label="Seleccionar todos en la página"
                className="rounded"
              />
            </th>
            <th className="px-4 py-3">Path</th>
            <th className="px-4 py-3 w-40">Estado</th>
            <th className="px-4 py-3 w-28">Severidad</th>
            <th className="px-4 py-3 w-40">Ejecución</th>
            <th className="px-4 py-3 w-48">Detectado</th>
            <th className="px-4 py-3 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isSuperseded = item.status === 'superseded'
            // D-1 del design: la severidad se codifica dos veces — banda de
            // borde izquierdo (canal de escaneo) y celda de texto canónico
            // (criterio de US-06). La banda va en el <tr> para que sobreviva
            // a las clases de fondo que `selected` y `superseded` ya usan.
            const severityMeta = getSeverityMeta(item.severity)
            const processContext = processContextLabel(item)
            return (
              <tr
                key={item.id}
                className={`border-b border-b-gray-700 border-l-4 hover:bg-gray-750 transition-colors ${
                  severityMeta.bandClass
                } ${isSuperseded ? 'opacity-60' : ''} ${
                  selected.has(item.id) ? 'bg-gray-700' : 'bg-gray-900'
                }`}
              >
                <td className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggleRow(item.id)}
                    aria-label={`Seleccionar evento #${item.id}`}
                    className="rounded"
                  />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      to={`/events/${item.id}`}
                      className="font-mono text-xs text-blue-400 hover:text-blue-300 break-all"
                    >
                      {item.path}
                    </Link>
                    {item.is_symlink && (
                      <span
                        title={`Symlink -> ${item.symlink_target ?? '?'}`}
                        className="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-cyan-900 text-cyan-300 shrink-0"
                      >
                        symlink
                      </span>
                    )}
                  </div>
                  {item.is_symlink && item.symlink_target && (
                    <div className="text-[11px] text-gray-500 font-mono break-all mt-0.5">
                      &rarr; {item.symlink_target}
                    </div>
                  )}
                  {/* Proceso causante (US-06): mismo registro tipográfico que ya
                      usa symlink_target arriba. Omitido por completo — ni vacío
                      ni con guiones — cuando los tres campos son null (:3.5/:3.6). */}
                  {processContext && (
                    <div className="text-[11px] text-gray-500 font-mono break-all mt-0.5">
                      {processContext}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${
                        STATUS_CLASSES[item.status] ?? 'bg-gray-700 text-gray-300'
                      }`}
                    >
                      {item.status}
                    </span>
                    {(() => {
                      const actionFailedMeta = getActionFailedMeta(item.action_failed)
                      if (!actionFailedMeta) return null
                      return (
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${actionFailedMeta.className}`}>
                          {actionFailedMeta.label}
                        </span>
                      )
                    })()}
                  </div>
                </td>
                <td className={`px-4 py-3 text-xs font-mono ${severityMeta.textClass}`}>
                  {item.severity}
                </td>
                <td className="px-4 py-3">
                  {(() => {
                    const ackMeta = getAckStatusMeta(item.ack_status)
                    if (!ackMeta) return null
                    return (
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${ackMeta.className}`}>
                        {item.ack_status}
                      </span>
                    )
                  })()}
                </td>
                <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                  {formatAbsolute(item.detected_at)}
                </td>
                <td className="px-4 py-3">
                  {/* Ícono de cadena para eventos superseded con link al padre */}
                  {isSuperseded && item.parent_event_id != null && (
                    <Link
                      to={`/events/${item.parent_event_id}`}
                      title={`Ver evento padre #${item.parent_event_id}`}
                      className="text-gray-500 hover:text-gray-300 text-xs"
                    >
                      <span aria-label="Evento superseded, ver cadena">&#128279;</span>
                    </Link>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
