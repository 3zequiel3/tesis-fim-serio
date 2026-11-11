import { Link } from 'react-router-dom'
import type { EventListItem } from '@/api/events'
import { formatAbsolute } from '@/utils/timeDisplay'
import { getSeverityMeta } from '@/utils/severity'
import { getEventTypeGapMeta } from '@/utils/eventType'
import { processContextLabel } from '@/utils/process'
import { PathLabel } from '@/components/ui/PathLabel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { EmptyState } from '@/components/ui/EmptyState'
import { ResponsiveTable, type Column } from '@/components/ui/ResponsiveTable'
import {
  ActionFailedBadge,
  AckStatusBadge,
  QuarantineStateBadge,
  SymlinkBadge,
} from '@/components/ui/EventIndicators'
import { Link2 } from 'lucide-react'

interface EventsTableProps {
  items: EventListItem[]
  selected: Set<number>
  onSelectionChange: (selected: Set<number>) => void
  /** Row checkboxes (bulk actions). Hidden for roles that cannot mutate. */
  selectable?: boolean
}

export function EventsTable({ items, selected, onSelectionChange, selectable = true }: EventsTableProps) {
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id))
  const someSelected = items.some((item) => selected.has(item.id))

  function toggleAll() {
    // Only the ids of the page that is visible right now (M9).
    const next = new Set(selected)
    if (allSelected) items.forEach((item) => next.delete(item.id))
    else items.forEach((item) => next.add(item.id))
    onSelectionChange(next)
  }

  function toggleRow(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelectionChange(next)
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="No hay eventos que coincidan con los filtros actuales."
        hint="Quitá algún filtro o ampliá el rango de fechas para ver más resultados."
      />
    )
  }

  const columns: Column<EventListItem>[] = [
    ...(selectable
      ? [
          {
            key: 'select',
            header: 'Seleccionar',
            hideHeader: true,
            className: 'w-10',
            cell: (item: EventListItem) => (
              <input
                type="checkbox"
                checked={selected.has(item.id)}
                onChange={() => toggleRow(item.id)}
                aria-label={`Seleccionar evento #${item.id}`}
                className="size-4 accent-accent"
              />
            ),
          },
        ]
      : []),
    {
      key: 'path',
      header: 'Ruta',
      primary: true,
      cell: (item) => {
        const processContext = processContextLabel(item)
        return (
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {/* D51/RN-145: the row stays navigable without a path; it branches on event_type. */}
              {item.path !== null ? (
                <Link to={`/events/${item.id}`} className="text-sm hover:underline">
                  <PathLabel path={item.path} />
                </Link>
              ) : (
                (() => {
                  const gapMeta = getEventTypeGapMeta(item.event_type)
                  return (
                    <Link
                      to={`/events/${item.id}`}
                      title={gapMeta.cause}
                      className={`inline-block shrink-0 rounded-control px-2 py-0.5 text-xs font-semibold hover:opacity-80 ${gapMeta.className}`}
                    >
                      {gapMeta.label}
                    </Link>
                  )
                })()
              )}
              <SymlinkBadge isSymlink={item.is_symlink} target={item.symlink_target} />
            </div>
            {item.is_symlink && item.symlink_target && (
              <div className="mt-0.5 flex items-center gap-1 font-mono text-xs text-text-muted [overflow-wrap:anywhere]">
                <Link2 aria-hidden="true" size={12} className="shrink-0" />
                {item.symlink_target}
              </div>
            )}
            {processContext && (
              <div className="mt-0.5 font-mono text-xs text-text-muted [overflow-wrap:anywhere]">{processContext}</div>
            )}
          </div>
        )
      },
    },
    {
      key: 'status',
      header: 'Estado',
      cell: (item) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={item.status} />
          <QuarantineStateBadge state={item.quarantine_state} />
          <ActionFailedBadge actionFailed={item.action_failed} />
        </div>
      ),
    },
    {
      key: 'severity',
      header: 'Severidad',
      cell: (item) => (
        <span className={`font-mono text-xs font-semibold ${getSeverityMeta(item.severity).textClass}`}>
          {item.severity}
        </span>
      ),
    },
    {
      key: 'ack',
      header: 'Ejecución',
      cell: (item) => <AckStatusBadge ackStatus={item.ack_status} variant="value" />,
    },
    {
      key: 'detected',
      header: 'Detectado',
      cell: (item) => (
        <span className="text-xs tabular-nums text-text-muted">{formatAbsolute(item.detected_at)}</span>
      ),
    },
    {
      key: 'chain',
      header: 'Cadena',
      hideHeader: true,
      cell: (item) =>
        item.status === 'superseded' && item.parent_event_id != null ? (
          <Link
            to={`/events/${item.parent_event_id}`}
            title={`Ver evento padre #${item.parent_event_id}`}
            aria-label="Evento superseded, ver cadena"
            className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-text"
          >
            <Link2 aria-hidden="true" size={14} />
            <span>#{item.parent_event_id}</span>
          </Link>
        ) : null,
    },
  ]

  return (
    <div>
      {selectable && (
        <label className="mb-2 flex w-fit cursor-pointer items-center gap-2 text-xs text-text-muted">
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected && !allSelected
            }}
            onChange={toggleAll}
            aria-label="Seleccionar todos en la página"
            className="size-4 accent-accent"
          />
          Seleccionar todos en la página
        </label>
      )}
      <ResponsiveTable
        caption="Eventos"
        columns={columns}
        rows={items}
        getRowKey={(item) => item.id}
        rowClassName={(item) =>
          // D-1: severity as a left band; it lives on the row so it survives the
          // background classes of `selected` and `superseded`.
          `border-l-4 ${getSeverityMeta(item.severity).bandClass} ${
            item.status === 'superseded' ? 'opacity-60' : ''
          } ${selected.has(item.id) ? 'bg-accent-soft' : ''}`
        }
      />
    </div>
  )
}
