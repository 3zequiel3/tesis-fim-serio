import type { ReactNode } from 'react'
import { readApiError } from '@/api/errors'
import { Button } from './Button'
import { EmptyState } from './EmptyState'

export const FORBIDDEN_MESSAGE = 'No tenés permiso para ver esta sección.'

interface DataStateProps {
  isLoading: boolean
  error?: unknown
  /** True when the query succeeded but there is nothing to show. */
  isEmpty?: boolean
  onRetry?: () => void
  /** What failed to load, for the error title: «los eventos», «las alertas». */
  resource?: string
  loadingLabel?: string
  emptyTitle?: string
  emptyHint?: string
  emptyAction?: ReactNode
  children: ReactNode
}

// One component for the three non-content states of every data view
// (D93/RN-187): loading, empty, and error with retry. A 403 never offers a
// retry; nothing stays in the loading state after an error.
export function DataState({
  isLoading,
  error,
  isEmpty = false,
  onRetry,
  resource = 'los datos',
  loadingLabel = 'Cargando…',
  emptyTitle = 'No hay nada para mostrar.',
  emptyHint,
  emptyAction,
  children,
}: DataStateProps) {
  if (error) {
    const apiError = readApiError(error)
    if (apiError.status === 403) {
      return (
        <div role="alert" className="rounded-panel border border-warning-line bg-warning-bg px-6 py-8 text-center text-warning-fg">
          {FORBIDDEN_MESSAGE}
        </div>
      )
    }
    return (
      <div role="alert" className="space-y-3 rounded-panel border border-danger-line bg-danger-bg px-6 py-8 text-center">
        <p className="font-semibold text-danger-fg">No se pudieron cargar {resource}.</p>
        {apiError.message && <p className="text-danger-fg">{apiError.message}</p>}
        {onRetry && (
          <Button variant="secondary" onClick={onRetry}>
            Reintentar
          </Button>
        )}
      </div>
    )
  }
  if (isLoading) {
    return (
      <div role="status" className="space-y-3 py-6" aria-live="polite">
        <p className="text-text-muted">{loadingLabel}</p>
        <div aria-hidden="true" className="space-y-2">
          <div className="h-9 animate-pulse rounded-control bg-surface-raised" />
          <div className="h-9 animate-pulse rounded-control bg-surface-raised opacity-70" />
          <div className="h-9 animate-pulse rounded-control bg-surface-raised opacity-40" />
        </div>
      </div>
    )
  }
  if (isEmpty) {
    return <EmptyState title={emptyTitle} hint={emptyHint} action={emptyAction} />
  }
  return <>{children}</>
}
