import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '@/api/client'

interface AlertsResponse {
  items: unknown[]
  total: number
  page: number
  size: number
}

export function AlertsBanner() {
  const { data } = useQuery<AlertsResponse>({
    queryKey: ['alerts-failed-count'],
    queryFn: () =>
      apiClient
        .get<AlertsResponse>('/alerts', { params: { status: 'failed', size: 1 } })
        .then((r) => r.data),
    refetchInterval: 30_000,
    retry: false,
  })

  if (!data || data.total === 0) return null

  return (
    <div
      role="alert"
      className="bg-yellow-400 text-yellow-900 text-center text-sm font-medium py-2 px-4"
    >
      {data.total} alerta{data.total !== 1 ? 's' : ''} fallida{data.total !== 1 ? 's' : ''} en la DLQ —{' '}
      <Link to="/alerts" className="underline font-semibold hover:text-yellow-800">
        revisar
      </Link>
    </div>
  )
}
