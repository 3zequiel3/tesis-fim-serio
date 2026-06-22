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

  const downComponents = data
    ? MONITORED.filter((name) => {
        const value = data[name]
        if (name === 'agents') return (value as { status: string }).status !== 'ok'
        return value !== 'ok'
      })
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
