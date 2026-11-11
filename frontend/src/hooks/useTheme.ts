import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'fim.theme'

const listeners = new Set<() => void>()

function serverTheme(): Theme {
  return 'dark'
}

function currentTheme(): Theme {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Applies a theme to <html> and persists the choice (design D-2). */
export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Storage may be blocked: the theme still applies for this page load.
  }
  listeners.forEach((l) => l())
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, currentTheme, serverTheme)
  const toggle = useCallback(() => {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark')
  }, [])
  return { theme, toggle }
}
