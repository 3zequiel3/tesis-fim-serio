import { useQuery } from '@tanstack/react-query'
import { getEvent, type EventDetail } from '@/api/events'

export function useEvent(id: number | null | undefined) {
  return useQuery<EventDetail>({
    queryKey: ['event', id],
    queryFn: () => getEvent(id as number),
    enabled: id != null,
    retry: (failureCount, error) => {
      // No reintentar en 404
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 404) return false
      return failureCount < 3
    },
  })
}
