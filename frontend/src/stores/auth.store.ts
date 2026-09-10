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
  logout: () => void
  refreshToken: () => Promise<void>
}

const REFRESH_EARLY_MS = 60_000
let refreshTimer: ReturnType<typeof setTimeout> | null = null

function cancelScheduledRefresh() {
  if (refreshTimer != null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function tokenExpirationMs(token: string): number | null {
  try {
    const encoded = token.split('.')[1]
    if (!encoded) return null
    const base64 = encoded.replaceAll('-', '+').replaceAll('_', '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof payload.exp === 'number' && Number.isFinite(payload.exp)
      ? payload.exp * 1000
      : null
  } catch {
    return null
  }
}

function scheduleRefresh(token: string) {
  cancelScheduledRefresh()
  const expiration = tokenExpirationMs(token)
  if (expiration == null) return

  // `exp` sin verificar sólo decide CUÁNDO intentar el refresh. Nunca concede
  // acceso: la autorización sigue dependiendo del JWT validado por el backend.
  const delay = Math.max(0, expiration - Date.now() - REFRESH_EARLY_MS)
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

  logout() {
    cancelScheduledRefresh()
    // Fire-and-forget: el backend invalida la cookie de refresh; errores de red se ignoran
    logoutApi().catch(() => undefined)
    set({ accessToken: null, user: null, isLoading: false })
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
      get().logout()
      throw err
    }
  },
}))
