import axios from 'axios'
import { useAuthStore } from '@/stores/auth.store'

// Grafo de dependencias (sin ciclo):
//   client.ts  →  auth.store.ts  →  api/auth.ts  (no importa client.ts)

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  withCredentials: true, // envía cookie fim_refresh automáticamente
})

// ─── Refresh token queue (D-FE-3) ────────────────────────────────────────────
let isRefreshing = false
let pendingQueue: Array<{
  resolve: (token: string) => void
  reject: (err: unknown) => void
}> = []

function processQueue(error: unknown, token: string | null) {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error)
    } else {
      resolve(token as string)
    }
  })
  pendingQueue = []
}

// ─── Request interceptor: adjunta Bearer token ────────────────────────────────
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// ─── Response interceptor: refresh automático en 401 ─────────────────────────
apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error)) {
      return Promise.reject(error)
    }

    const originalRequest = error.config as typeof error.config & {
      _retry?: boolean
    }

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry
    ) {
      if (isRefreshing) {
        // Encolar hasta que el refresh en curso termine
        return new Promise<string>((resolve, reject) => {
          pendingQueue.push({ resolve, reject })
        }).then((token) => {
          if (originalRequest.headers) {
            originalRequest.headers['Authorization'] = `Bearer ${token}`
          }
          return apiClient(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post<{
          access_token: string
          user?: { id: number; username: string; role: string }
        }>('/auth/refresh', {}, { baseURL: BASE_URL, withCredentials: true })

        const newToken = data.access_token
        const currentUser = useAuthStore.getState().user
        useAuthStore.getState().setToken(newToken, data.user ?? currentUser)

        processQueue(null, newToken)

        if (originalRequest.headers) {
          originalRequest.headers['Authorization'] = `Bearer ${newToken}`
        }
        return apiClient(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        useAuthStore.getState().logout()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  },
)

export default apiClient
