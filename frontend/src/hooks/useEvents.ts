import { useQuery } from '@tanstack/react-query'
import { getEvents, type EventFilters, type EventListResponse } from '@/api/events'

export function useEvents(filters: EventFilters = {}) {
  return useQuery<EventListResponse>({
    queryKey: ['events', filters],
    queryFn: () => getEvents(filters),
    placeholderData: (prev) => prev,
  })
}
