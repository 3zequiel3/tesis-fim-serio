import { create } from 'zustand'
import { loginApi, logoutApi, refreshApi } from '@/api/auth'
import type { LoginCredentials, AuthUser } from '@/api/auth'

// NUNCA usar persist middleware — el access token solo vive en RAM (RN-96, D-FE-2)

export interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  isLoading: boolean

  // Acciones
  setToken: (token: string, user: AuthUser | null) => void
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => Promise<boolean>
  refreshToken: () => Promise<void>
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
    void useAuthStore.getState().refreshToken().catch(() => undefined)
  }, delay)
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isLoading: false,

  setToken(token: string, user: AuthUser | null) {
    scheduleRefresh(token)
    set({ accessToken: token, user: user ?? null })
  },

  async login(credentials: LoginCredentials) {
    set({ isLoading: true })
    try {
      const data = await loginApi(credentials)
      scheduleRefresh(data.access_token)
      set({ accessToken: data.access_token, user: data.user, isLoading: false })
    } catch (err) {
      set({ isLoading: false })
      throw err
    }
  },

  async logout() {
    const accessToken = get().accessToken
    cancelScheduledRefresh()
    set({ accessToken: null, user: null, isLoading: false })
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
    set({ isLoading: true })
    try {
      const data = await refreshApi()
      scheduleRefresh(data.access_token)
      set({
        accessToken: data.access_token,
        user: data.user,
        isLoading: false,
      })
    } catch (err) {
      // Un refresh expirado, revocado o fallido no deja una sesión fantasma.
      // ProtectedRoute observa la pérdida del token y navega a login.
      await get().logout()
      throw err
    }
  },
}))
