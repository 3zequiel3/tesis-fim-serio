import { useQuery } from '@tanstack/react-query'
import { getEvents, type EventFilters, type EventListResponse } from '@/api/events'

// D93/RN-187: the list stays current without a reload. The SSE feed invalidates
// ['events'] on every alert; this interval is the fallback while the tab is visible.
export const EVENTS_REFETCH_MS = 15_000

/**
 * The key carries the (already debounced) filters, so a late response for an
 * older filter value lands in its own cache entry and never replaces the
 * current one (M9).
 */
export function useEvents(filters: EventFilters = {}) {
  return useQuery<EventListResponse>({
    queryKey: ['events', filters],
    queryFn: () => getEvents(filters),
    placeholderData: (prev) => prev,
    refetchInterval: EVENTS_REFETCH_MS,
    refetchIntervalInBackground: false,
  })
}
