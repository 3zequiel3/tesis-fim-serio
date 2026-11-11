import { create } from 'zustand'
import { loginApi, logoutApi, refreshApi } from '@/api/auth'
import type { LoginCredentials, AuthUser } from '@/api/auth'
import { queryClient } from '@/api/queryClient'

// NUNCA usar persist middleware — el access token solo vive en RAM (RN-96, D-FE-2)

/** Why the local session ended (design D-5). Drives the notice shown at /login. */
export type SessionEndReason = 'logout' | 'expired' | 'password_changed'

export const SESSION_EXPIRED_NOTICE = 'Tu sesión venció. Ingresá de nuevo.'
export const PASSWORD_CHANGED_NOTICE = 'Contraseña actualizada. Ingresá con la contraseña nueva.'

export interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  /** True only while a login request is in flight. A token renewal never sets it. */
  isLoading: boolean
  /** Set by endSession(); the router guard reads it to pick the notice for /login. */
  endedReason: SessionEndReason | null

  // Acciones
  setToken: (token: string, user: AuthUser | null) => void
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => Promise<boolean>
  /**
   * Renews the access token. It never touches `isLoading`: ProtectedRoute and
   * every page keep their state while a (proactive) renewal runs (B4).
   */
  refreshToken: () => Promise<void>
  /** Clears the store AND the query cache, so no data outlives the session (M1). */
  endSession: (reason: SessionEndReason) => void
  clearEndedReason: () => void
}

const REFRESH_EARLY_MS = 60_000
const MIN_REFRESH_DELAY_MS = 1_000
const MAX_REFRESH_DELAY_MS = 60 * 60 * 1_000
let refreshTimer: ReturnType<typeof setTimeout> | null = null

function cancelScheduledRefresh() {
  if (refreshTimer != null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function tokenRefreshDelayMs(token: string): number | null {
  try {
    const encoded = token.split('.')[1]
    if (!encoded) return null
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as { iat?: unknown; exp?: unknown }
    if (
      typeof payload.iat !== 'number' || !Number.isFinite(payload.iat) ||
      typeof payload.exp !== 'number' || !Number.isFinite(payload.exp) ||
      payload.exp <= payload.iat
    ) return null

    const hintedLifetimeMs = (payload.exp - payload.iat) * 1_000
    const hintedDelayMs = hintedLifetimeMs - REFRESH_EARLY_MS
    return Math.min(MAX_REFRESH_DELAY_MS, Math.max(MIN_REFRESH_DELAY_MS, hintedDelayMs))
  } catch {
    return null
  }
}

function scheduleRefresh(token: string) {
  cancelScheduledRefresh()
  const delay = tokenRefreshDelayMs(token)
  if (delay == null) return

  // `exp - iat` sin verificar sólo aporta una DURACIÓN desde la recepción.
  // Así el clock skew del cliente no convierte cada token nuevo en un timer
  // inmediato. El clamp evita loops y timers absurdamente largos; si los
  // hints son inválidos, queda el fallback reactivo ante 401. Ningún claim
  // local concede acceso: la autorización sigue dependiendo del backend.
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    // A failed proactive renewal means the session is gone: end it with the
    // «expired» notice instead of leaving a ghost session.
    useAuthStore
      .getState()
      .refreshToken()
      .catch(() => {
        useAuthStore.getState().endSession('expired')
      })
  }, delay)
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isLoading: false,
  endedReason: null,

  setToken(token: string, user: AuthUser | null) {
    scheduleRefresh(token)
    set({ accessToken: token, user: user ?? null })
  },

  async login(credentials: LoginCredentials) {
    set({ isLoading: true })
    try {
      const data = await loginApi(credentials)
      scheduleRefresh(data.access_token)
      set({
        accessToken: data.access_token,
        user: data.user,
        isLoading: false,
        endedReason: null,
      })
    } catch (err) {
      set({ isLoading: false })
      throw err
    }
  },

  endSession(reason: SessionEndReason) {
    cancelScheduledRefresh()
    queryClient.clear()
    set({ accessToken: null, user: null, isLoading: false, endedReason: reason })
  },

  clearEndedReason() {
    set({ endedReason: null })
  },

  async logout() {
    const accessToken = get().accessToken
    get().endSession('logout')
    if (!accessToken) return true
    try {
      await logoutApi(accessToken)
      return true
    } catch {
      // La sesión local se elimina aunque la red falle, pero el llamador recibe
      // un resultado explícito para no presentar la revocación remota como exitosa.
      return false
    }
  },

  async refreshToken() {
    try {
      const data = await refreshApi()
      scheduleRefresh(data.access_token)
      set({ accessToken: data.access_token, user: data.user })
    } catch (err) {
      // Un refresh expirado, revocado o fallido no deja una sesión fantasma.
      // El llamador decide el aviso: la verificación inicial sin cookie vuelve
      // a /login sin aviso; la renovación en segundo plano usa «expired».
      cancelScheduledRefresh()
      set({ accessToken: null, user: null })
      throw err
    }
  },
}))
