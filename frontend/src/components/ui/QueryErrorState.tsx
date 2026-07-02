interface QueryErrorStateProps {
  /** Nombre del recurso que falló, para el mensaje ("los eventos", "las alertas"...) */
  resource: string
  onRetry: () => void
}

/**
 * Estado de error compartido para las páginas de listado (C38).
 * Antes las páginas solo manejaban isLoading: si la request fallaba,
 * quedaba una pantalla muda sin feedback ni forma de reintentar.
 */
export function QueryErrorState({ resource, onRetry }: QueryErrorStateProps) {
  return (
    <div role="alert" className="py-12 text-center space-y-3">
      <p className="text-sm text-red-400">
        No se pudieron cargar {resource}. Verificá tu conexión o reintentá.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="px-4 py-1.5 bg-primary hover:bg-primary-hover text-white text-sm rounded"
      >
        Reintentar
      </button>
    </div>
  )
}
