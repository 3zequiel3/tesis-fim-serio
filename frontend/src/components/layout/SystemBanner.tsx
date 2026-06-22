import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'

// Shape real del backend: GET /health/components retorna un objeto plano
interface HealthResponse {
  postgres: string
  valkey: string
  n8n: string
  agents: string
}

export function SystemBanner() {
  const { data } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => apiClient.get<HealthResponse>('/health/components').then((r) => r.data),
    refetchInterval: 10_000,
    // No mostrar error — si falla el health check, simplemente no mostramos banner
    retry: false,
  })

  // Iterar sobre los valores del objeto plano para detectar componentes no-ok
  const downComponents = data
    ? Object.entries(data)
        .filter(([, status]) => status !== 'ok')
        .map(([name]) => name)
    : []

  if (downComponents.length === 0) return null

  return (
    <div
      role="alert"
      className="bg-red-600 text-white text-center text-sm font-medium py-2 px-4"
    >
      Sistema degradado —{' '}
      {downComponents.join(', ')} no disponible
    </div>
  )
}
