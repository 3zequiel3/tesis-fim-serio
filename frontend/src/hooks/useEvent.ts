import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getEvent, type EventDetail } from '@/api/events'
import { readApiError } from '@/api/errors'

// D93/RN-187 (design D-7): while the last command of the event is `pending`,
// re-read the detail every 3 s for at most 60 s. The backend marks a command as
// timed out at 5 minutes, so after 60 s the user gets «Actualizar» instead.
export const COMMAND_POLL_INTERVAL_MS = 3_000
export const COMMAND_POLL_WINDOW_MS = 60_000

export function useEvent(id: number | null | undefined) {
  // When the current pending episode started; written only from the interval callback.
  const pendingSinceRef = useRef<number | null>(null)
  const [restartKey, setRestartKey] = useState(0)
  const [pollingStopped, setPollingStopped] = useState(false)

  const query = useQuery<EventDetail>({
    queryKey: ['event', id],
    queryFn: () => getEvent(id as number),
    enabled: id != null,
    retry: (failureCount, error) => {
      // A 4xx will not change by asking again (404, 403); a network/5xx blip gets one retry.
      const { status } = readApiError(error)
      if (status >= 400 && status < 500) return false
      return failureCount < 1
    },
    retryDelay: 300,
    refetchInterval: (q) => {
      if (q.state.data?.ack_status !== 'pending') {
        pendingSinceRef.current = null
        return false
      }
      pendingSinceRef.current ??= Date.now()
      return Date.now() - pendingSinceRef.current < COMMAND_POLL_WINDOW_MS ? COMMAND_POLL_INTERVAL_MS : false
    },
    // A hidden tab does not need to poll; it catches up when it becomes visible.
    refetchIntervalInBackground: false,
  })

  const commandPending = query.data?.ack_status === 'pending'

  useEffect(() => {
    if (!commandPending) return
    const timer = setTimeout(() => setPollingStopped(true), COMMAND_POLL_WINDOW_MS)
    return () => {
      clearTimeout(timer)
      setPollingStopped(false)
    }
  }, [commandPending, restartKey])

  function restartPolling() {
    pendingSinceRef.current = Date.now()
    setRestartKey((k) => k + 1)
    void query.refetch()
  }

  return { ...query, pollingStopped: commandPending && pollingStopped, restartPolling }
}
