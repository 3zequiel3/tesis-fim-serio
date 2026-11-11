import { useCallback, useSyncExternalStore } from 'react'

/**
 * Tracks a CSS media query. Where matchMedia does not exist (older test
 * environments) it reports `fallback`, so desktop markup is the default.
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== 'function') return () => undefined
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    [query],
  )
  const getSnapshot = () =>
    typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : fallback
  return useSyncExternalStore(subscribe, getSnapshot, () => fallback)
}
