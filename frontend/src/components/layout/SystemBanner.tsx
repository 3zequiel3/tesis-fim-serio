import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'

interface HealthResponse {
  postgres: string
  valkey: string
  n8n: string
  agents: { status: string; items: unknown[] }
  checked_at: string
}

const MONITORED: Array<keyof Omit<HealthResponse, 'checked_at'>> = [
  'postgres',
  'valkey',
  'n8n',
  'agents',
]

export function SystemBanner() {
  const { data } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => apiClient.get<HealthResponse>('/health/components').then((r) => r.data),
    refetchInterval: 10_000,
    retry: false,
  })

  // US-28 criterio 3: el banner debe mostrar el timestamp del ULTIMO check
  // saludable de cada componente, no el del poll actual (que, mientras el
  // banner esta visible, es siempre un poll degradado). Se guarda por
  // componente para que un componente que se recupera no pise el timestamp
  // de otro que sigue caido.
  const lastHealthyAtRef = useRef<Partial<Record<string, string>>>({})

  // US-28 criterio 4: cerrable manualmente, pero reaparece en el siguiente
  // poll si la condicion persiste. Se guarda el `checked_at` del poll que el
  // usuario cerro; en cuanto llega un poll con un `checked_at` distinto, el
  // banner vuelve a evaluarse desde cero.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    for (const name of MONITORED) {
      const value = data[name]
      const status = name === 'agents' ? (value as { status: string }).status : (value as string)
      if (status === 'ok') {
        lastHealthyAtRef.current[name] = data.checked_at
      }
    }
  }, [data])

  const downComponents = data
    ? MONITORED.filter((name) => {
        const value = data[name]
        if (name === 'agents') return (value as { status: string }).status !== 'ok'
        return value !== 'ok'
      })
    : []

  if (downComponents.length === 0) return null
  if (data && dismissedFor === data.checked_at) return null

  return (
    <div
      role="alert"
      className="bg-red-600 text-white text-center text-sm font-medium py-2 px-4 flex items-center justify-center gap-3"
    >
      <span>
        Sistema degradado —{' '}
        {downComponents
          .map((name) => {
            const lastHealthy = lastHealthyAtRef.current[name]
            return lastHealthy ? `${name} (última vez saludable: ${lastHealthy})` : name
          })
          .join(', ')}{' '}
        no disponible
      </span>
      <button
        type="button"
        aria-label="Cerrar aviso de degradación"
        onClick={() => data && setDismissedFor(data.checked_at)}
        className="text-white/80 hover:text-white font-bold px-1"
      >
        Cerrar
      </button>
    </div>
  )
}
