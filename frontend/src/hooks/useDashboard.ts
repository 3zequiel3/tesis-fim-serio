import { useQuery } from '@tanstack/react-query'
import { getDashboardSummary } from '@/api/dashboard'

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboardSummary,
    refetchInterval: 30_000,
  })
}
