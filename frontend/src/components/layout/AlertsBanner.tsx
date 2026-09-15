import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '@/api/client'

interface FailedAlertsCountResponse {
  count: number
}

export function AlertsBanner() {
  const { data } = useQuery<FailedAlertsCountResponse>({
    queryKey: ['alerts', 'failed', 'count'],
    queryFn: () =>
      apiClient.get<FailedAlertsCountResponse>('/alerts/failed/count').then((r) => r.data),
    refetchInterval: 30_000,
    retry: false,
  })

  const count = data?.count ?? 0
  if (count === 0) return null

  return (
    <div
      role="alert"
      className="bg-yellow-400 text-yellow-900 text-center text-sm font-medium py-2 px-4"
    >
      Notificaciones pendientes: {count} alerta{count !== 1 ? 's' : ''}{' '}
      {count !== 1 ? 'no pudieron ser enviadas' : 'no pudo ser enviada'} —{' '}
      <Link to="/alerts/failed" className="underline font-semibold hover:text-yellow-800">
        revisar
      </Link>
    </div>
  )
}
