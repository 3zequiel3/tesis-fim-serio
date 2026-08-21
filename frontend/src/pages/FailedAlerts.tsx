import { useState } from 'react'
import { toast } from 'sonner'
import axios from 'axios'
import { useFailedAlerts, useRetryAlert, useDiscardAlert } from '@/hooks/useAlerts'
import { QueryErrorState } from '@/components/ui/QueryErrorState'
import { formatAbsolute } from '@/utils/timeDisplay'
import type { Alert } from '@/api/alerts'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-red-400',
  high: 'text-orange-400',
  medium: 'text-yellow-400',
  low: 'text-blue-400',
}

// ─── Página ───────────────────────────────────────────────────────────────────

export function FailedAlerts() {
  const { data: alerts, isLoading, isError, refetch } = useFailedAlerts()
  const retryMutation = useRetryAlert()
  const discardMutation = useDiscardAlert()

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [discardingId, setDiscardingId] = useState<number | null>(null)
  const [bulkRetrying, setBulkRetrying] = useState(false)

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function toggleSelectAll(items: Alert[]) {
    if (selected.size === items.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map((a) => a.id)))
    }
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
        const msg = axios.isAxiosError(err)
          ? err.response?.data?.detail ?? err.message
          : String(err)
        toast.error(`Error al reintentar alerta ${id}: ${msg}`)
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
          .catch(() => failed++)
      )
    )
    setBulkRetrying(false)
    setSelected(new Set())
    if (succeeded > 0) toast.success(`${succeeded} alerta${succeeded !== 1 ? 's' : ''} reintentada${succeeded !== 1 ? 's' : ''}`)
    if (failed > 0) toast.error(`${failed} alerta${failed !== 1 ? 's' : ''} fallaron`)
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
        const msg = axios.isAxiosError(err)
          ? err.response?.data?.detail ?? err.message
          : String(err)
        toast.error(`Error al descartar alerta ${id}: ${msg}`)
        setDiscardingId(null)
      },
    })
  }

  const allSelected = alerts && alerts.length > 0 && selected.size === alerts.length

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Alertas fallidas</h1>
        {alerts && alerts.length > 0 && (
          <span className="text-xs text-gray-500">
            {alerts.length} alerta{alerts.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-4 bg-gray-800 border border-gray-700 rounded px-4 py-2.5">
          <span className="text-sm text-gray-300">
            {selected.size} seleccionada{selected.size !== 1 ? 's' : ''}
          </span>
          <button
            onClick={handleBulkRetry}
            disabled={bulkRetrying}
            className="px-4 py-1.5 bg-primary hover:bg-primary-hover text-white text-sm rounded disabled:opacity-40"
          >
            {bulkRetrying ? 'Reintentando...' : 'Reintentar seleccionadas'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-gray-400 hover:text-gray-200"
          >
            Limpiar selección
          </button>
        </div>
      )}

      {/* Tabla */}
      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando alertas fallidas...</div>
      ) : isError ? (
        <QueryErrorState resource="las alertas fallidas" onRetry={() => refetch()} />
      ) : !alerts || alerts.length === 0 ? (
        <div className="py-12 text-center text-gray-500">
          <p className="text-sm">No hay alertas fallidas.</p>
        </div>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-400">
                <th className="px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={!!allSelected}
                    onChange={() => toggleSelectAll(alerts)}
                    className="rounded"
                  />
                </th>
                <th className="text-left px-4 py-2.5">ID</th>
                <th className="text-left px-4 py-2.5">Severidad</th>
                <th className="text-left px-4 py-2.5">Canal</th>
                <th className="text-left px-4 py-2.5">Fallada</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {alerts.map((alert) => (
                <tr
                  key={alert.id}
                  className={`hover:bg-gray-750 ${selected.has(alert.id) ? 'bg-blue-950/20' : ''}`}
                >
                  <td className="px-3 py-2.5 text-center">
                    <input
                      type="checkbox"
                      checked={selected.has(alert.id)}
                      onChange={() => toggleSelect(alert.id)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 tabular-nums">{alert.id}</td>
                  <td className={`px-4 py-2.5 font-medium ${SEVERITY_COLORS[alert.severity] ?? 'text-gray-300'}`}>
                    {alert.severity}
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">{alert.channel}</td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">
                    {formatAbsolute(alert.failed_at, { nullLabel: '—' })}
                  </td>
                  <td className="px-4 py-2.5">
                    {discardingId === alert.id ? (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-gray-400">¿Descartar?</span>
                        <button
                          onClick={() => handleDiscard(alert.id)}
                          disabled={discardMutation.isPending}
                          className="text-red-400 hover:text-red-300 disabled:opacity-40"
                        >
                          Confirmar
                        </button>
                        <button
                          onClick={() => setDiscardingId(null)}
                          className="text-gray-500 hover:text-gray-300"
                        >
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-3 justify-end">
                        <button
                          onClick={() => handleRetry(alert.id)}
                          disabled={retryMutation.isPending}
                          className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
                        >
                          Reintentar
                        </button>
                        <button
                          onClick={() => setDiscardingId(alert.id)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          Descartar
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
