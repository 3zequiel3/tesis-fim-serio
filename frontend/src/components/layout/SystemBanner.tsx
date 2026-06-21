import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'

interface HealthComponent {
  name: string
  status: 'ok' | 'degraded' | 'down'
}

interface HealthResponse {
  components: HealthComponent[]
}

export function SystemBanner() {
  const { data } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => apiClient.get<HealthResponse>('/health/components').then((r) => r.data),
    refetchInterval: 10_000,
    // No mostrar error — si falla el health check, simplemente no mostramos banner
    retry: false,
  })

  const downComponents = data?.components.filter((c) => c.status === 'down') ?? []

  if (downComponents.length === 0) return null

  return (
    <div
      role="alert"
      className="bg-red-600 text-white text-center text-sm font-medium py-2 px-4"
    >
      Sistema degradado —{' '}
      {downComponents.map((c) => c.name).join(', ')} no disponible
    </div>
  )
}
