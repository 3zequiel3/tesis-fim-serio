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

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isLoading: false,

  setToken(token: string, user: AuthUser | null) {
    set({ accessToken: token, user: user ?? null })
  },

  async login(credentials: LoginCredentials) {
    set({ isLoading: true })
    try {
      const data = await loginApi(credentials)
      set({ accessToken: data.access_token, user: data.user, isLoading: false })
    } catch (err) {
      set({ isLoading: false })
      throw err
    }
  },

  logout() {
    // Fire-and-forget: el backend invalida la cookie de refresh; errores de red se ignoran
    logoutApi().catch(() => undefined)
    set({ accessToken: null, user: null, isLoading: false })
  },

  async refreshToken() {
    set({ isLoading: true })
    try {
      const data = await refreshApi()
      set({
        accessToken: data.access_token,
        user: data.user,
        isLoading: false,
      })
    } catch (err) {
      set({ isLoading: false })
      throw err
    }
  },
}))
