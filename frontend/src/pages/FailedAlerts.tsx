import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { useFailedAlerts, useRetryAlert, useDiscardAlert } from '@/hooks/useAlerts'
import { Can } from '@/hooks/useCan'
import { retryAlert } from '@/api/alerts'
import { apiErrorMessage } from '@/api/errors'
import { Button } from '@/components/ui/Button'
import { DataState } from '@/components/ui/DataState'
import { ResponsiveTable, type Column } from '@/components/ui/ResponsiveTable'
import { formatAbsolute } from '@/utils/timeDisplay'
import { getSeverityMeta } from '@/utils/severity'
import type { Alert } from '@/api/alerts'

const MAX_ERROR_CHARS = 60

function truncate(text: string): string {
  return text.length > MAX_ERROR_CHARS ? `${text.slice(0, MAX_ERROR_CHARS)}…` : text
}

// ─── Página ───────────────────────────────────────────────────────────────────

export function FailedAlerts() {
  const queryClient = useQueryClient()
  const { data: alerts, isLoading, error, refetch } = useFailedAlerts()
  const retryMutation = useRetryAlert()
  const discardMutation = useDiscardAlert()

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [discardingId, setDiscardingId] = useState<number | null>(null)
  const [bulkRetrying, setBulkRetrying] = useState(false)
  const [retryAllSummary, setRetryAllSummary] = useState<string | null>(null)

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll(items: Alert[]) {
    setSelected(selected.size === items.length ? new Set() : new Set(items.map((a) => a.id)))
  }

  function handleRetry(id: number) {
    retryMutation.mutate(id, {
      onSuccess: () => {
        toast.success(`Alerta ${id} re-enviada`)
        setSelected((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      },
      onError: (err) => {
        toast.error(`Error al reintentar alerta ${id}: ${apiErrorMessage(err, 'no se pudo reintentar')}`)
      },
    })
  }

  async function handleBulkRetry() {
    const ids = Array.from(selected)
    if (ids.length === 0) return
    setBulkRetrying(true)
    let succeeded = 0
    let failed = 0
    await Promise.allSettled(
      ids.map((id) =>
        retryMutation
          .mutateAsync(id)
          .then(() => succeeded++)
          .catch(() => failed++),
      ),
    )
    setBulkRetrying(false)
    setSelected(new Set())
    if (succeeded > 0) toast.success(`${succeeded} alerta${succeeded !== 1 ? 's' : ''} reintentada${succeeded !== 1 ? 's' : ''}`)
    if (failed > 0) toast.error(`${failed} alerta${failed !== 1 ? 's' : ''} fallaron`)
  }

  // D93/RN-187 (B8): retries every listed alert, one after another so the
  // delivery channel is not hit in parallel, then reports the outcome.
  async function handleRetryAll(items: Alert[]) {
    setBulkRetrying(true)
    setRetryAllSummary(null)
    let succeeded = 0
    let failed = 0
    for (const alert of items) {
      try {
        await retryAlert(alert.id)
        succeeded++
      } catch {
        failed++
      }
    }
    setBulkRetrying(false)
    setSelected(new Set())
    const summary = `Reintento terminado: ${succeeded} correcta${succeeded !== 1 ? 's' : ''}, ${failed} fallida${failed !== 1 ? 's' : ''}.`
    setRetryAllSummary(summary)
    if (failed === 0) toast.success(summary)
    else toast.warning(summary)
    // Refreshes the list and, through the shared prefix, the banner count.
    await queryClient.invalidateQueries({ queryKey: ['alerts'] })
  }

  function handleDiscard(id: number) {
    discardMutation.mutate(id, {
      onSuccess: () => {
        toast.success(`Alerta ${id} descartada`)
        setDiscardingId(null)
        setSelected((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      },
      onError: (err) => {
        toast.error(`Error al descartar alerta ${id}: ${apiErrorMessage(err, 'no se pudo descartar')}`)
        setDiscardingId(null)
      },
    })
  }

  const allSelected = !!alerts && alerts.length > 0 && selected.size === alerts.length

  const columns: Column<Alert>[] = [
    {
      key: 'select',
      header: 'Seleccionar',
      hideHeader: true,
      className: 'w-10',
      cell: (a) => (
        <Can>
          <input
            type="checkbox"
            checked={selected.has(a.id)}
            onChange={() => toggleSelect(a.id)}
            aria-label={`Seleccionar alerta ${a.id}`}
            className="size-4 accent-accent"
          />
        </Can>
      ),
    },
    { key: 'id', header: 'ID', cell: (a) => <span className="tabular-nums text-text-muted">{a.id}</span> },
    {
      key: 'event',
      header: 'Evento',
      primary: true,
      cell: (a) => (
        <Link to={`/events/${a.event_id}`} className="font-semibold text-accent underline">
          Evento #{a.event_id}
        </Link>
      ),
    },
    {
      key: 'severity',
      header: 'Severidad',
      cell: (a) => <span className={`font-semibold ${getSeverityMeta(a.severity).textClass}`}>{a.severity}</span>,
    },
    {
      key: 'channel',
      header: 'Canal',
      cell: (a) => (
        <span className={a.channel ? 'font-mono text-xs text-text-muted' : 'text-xs italic text-text-muted'}>
          {a.channel ?? 'sin canal entregado'}
        </span>
      ),
    },
    {
      key: 'retries',
      header: 'Reintentos',
      cell: (a) => <span className="tabular-nums text-text-muted">{a.retry_count ?? 0}</span>,
    },
    {
      key: 'error',
      header: 'Último error',
      cell: (a) =>
        a.last_error ? (
          <span title={a.last_error} className="font-mono text-xs text-danger-fg [overflow-wrap:anywhere]">
            {truncate(a.last_error)}
          </span>
        ) : (
          <span className="text-text-muted">—</span>
        ),
    },
    {
      key: 'failed',
      header: 'Fallada',
      cell: (a) => <span className="text-xs text-text-muted">{formatAbsolute(a.failed_at, { nullLabel: '—' })}</span>,
    },
    {
      key: 'actions',
      header: 'Acciones',
      hideHeader: true,
      cell: (a) => (
        <Can>
          {discardingId === a.id ? (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-text-muted">¿Descartar?</span>
              <Button variant="danger" size="sm" onClick={() => handleDiscard(a.id)} disabled={discardMutation.isPending}>
                Confirmar
              </Button>
              <Button size="sm" onClick={() => setDiscardingId(null)}>
                Cancelar
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2 sm:justify-end">
              <Button size="sm" onClick={() => handleRetry(a.id)} disabled={retryMutation.isPending || bulkRetrying}>
                Reintentar
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDiscardingId(a.id)}>
                Descartar
              </Button>
            </div>
          )}
        </Can>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-text">Alertas fallidas</h1>
        <div className="flex items-center gap-3">
          {alerts && alerts.length > 0 && (
            <span className="text-xs text-text-muted">
              {alerts.length} alerta{alerts.length !== 1 ? 's' : ''}
            </span>
          )}
          {alerts && alerts.length > 0 && (
            <Can>
              <Button variant="primary" onClick={() => void handleRetryAll(alerts)} loading={bulkRetrying}>
                Reintentar todas
              </Button>
            </Can>
          )}
        </div>
      </div>

      {retryAllSummary && (
        <p role="status" className="rounded-control border border-line bg-surface-raised px-3 py-2 text-text">
          {retryAllSummary}
        </p>
      )}

      {selected.size > 0 && (
        <Can>
          <div className="flex flex-wrap items-center gap-4 rounded-panel border border-accent bg-accent-soft px-4 py-2.5">
            <span className="font-semibold text-accent-soft-text">
              {selected.size} seleccionada{selected.size !== 1 ? 's' : ''}
            </span>
            <Button variant="primary" size="sm" onClick={() => void handleBulkRetry()} disabled={bulkRetrying}>
              {bulkRetrying ? 'Reintentando...' : 'Reintentar seleccionadas'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
              Limpiar selección
            </Button>
          </div>
        </Can>
      )}

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="las alertas fallidas"
        loadingLabel="Cargando alertas fallidas..."
        isEmpty={!alerts || alerts.length === 0}
        emptyTitle="No hay alertas fallidas."
        emptyHint="Las notificaciones que no se puedan entregar aparecen acá para reintentarlas."
      >
        {alerts && (
          <>
            <Can>
              <label className="mb-2 flex w-fit cursor-pointer items-center gap-2 text-xs text-text-muted">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => toggleSelectAll(alerts)}
                  aria-label="Seleccionar todas"
                  className="size-4 accent-accent"
                />
                Seleccionar todas
              </label>
            </Can>
            <ResponsiveTable caption="Alertas fallidas" columns={columns} rows={alerts} getRowKey={(a) => a.id} />
          </>
        )}
      </DataState>
    </div>
  )
}
