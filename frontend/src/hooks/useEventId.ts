import { useParams } from 'react-router-dom'

const POSITIVE_INTEGER = /^[1-9]\d*$/

/**
 * The `:id` route param as a number, or null when it is not a positive
 * integer (D93/RN-187). A null id keeps the query disabled, so `/events/abc`
 * never sends `GET /events/NaN`.
 */
export function useEventId(): number | null {
  const { id } = useParams<{ id: string }>()
  if (id == null || !POSITIVE_INTEGER.test(id)) return null
  const parsed = Number(id)
  return Number.isSafeInteger(parsed) ? parsed : null
}
