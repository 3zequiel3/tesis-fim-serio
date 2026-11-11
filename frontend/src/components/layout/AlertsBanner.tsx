import { useQuery } from '@tanstack/react-query'
import { BellRing } from 'lucide-react'
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
      className="flex items-center justify-center gap-2 border-b border-warning-line bg-warning-bg px-4 py-2 text-center font-semibold text-warning-fg"
    >
      <BellRing aria-hidden="true" size={18} className="shrink-0" />
      <span>
        Notificaciones pendientes: {count} alerta{count !== 1 ? 's' : ''}{' '}
        {count !== 1 ? 'no pudieron ser enviadas' : 'no pudo ser enviada'} —{' '}
        <Link to="/alerts/failed" className="underline hover:opacity-80">
          revisar
        </Link>
      </span>
    </div>
  )
}
