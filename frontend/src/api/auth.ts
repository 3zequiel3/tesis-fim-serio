import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Instancia propia para rutas de auth — no usa apiClient para evitar ciclos ESM.
// Para requests que necesitan Bearer token (changePassword) se adjunta
// manualmente leyendo el store via getState().
const authAxios = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
})

export interface LoginCredentials {
  username: string
  password: string
}

// Contrato C38 (FIX-01): el backend embebe el usuario autenticado en las
// respuestas de login y refresh (AuthUserOut en auth/schemas.py).
export interface AuthUser {
  id: number
  username: string
  role: string
  must_change_password: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: string
  must_change_password: boolean
  user: AuthUser
}

export interface RefreshResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

export async function loginApi(credentials: LoginCredentials): Promise<LoginResponse> {
  const { data } = await authAxios.post<LoginResponse>('/auth/login', credentials)
  return data
}

// Single-flight: dedupe los refreshes concurrentes en una sola request. Sin esto,
// al recargar la página las queries que dan 401 + el refresh de ProtectedRoute
// disparan varios /auth/refresh en paralelo con el MISMO refresh token; la
// rotación single-use del backend blacklistea el primero y los demás reciben
// "Refresh token revoked" → deslogueo espurio. Todos los llamadores comparten la
// promesa en curso.
let inFlightRefresh: Promise<RefreshResponse> | null = null

export async function refreshApi(): Promise<RefreshResponse> {
  if (inFlightRefresh) return inFlightRefresh
  inFlightRefresh = authAxios
    .post<RefreshResponse>('/auth/refresh')
    .then((r) => r.data)
    .finally(() => {
      inFlightRefresh = null
    })
  return inFlightRefresh
}

export async function logoutApi(): Promise<void> {
  await authAxios.post('/auth/logout')
}

export interface ChangePasswordPayload {
  new_password: string
}

export async function changePasswordApi(
  payload: ChangePasswordPayload,
  token: string,
): Promise<void> {
  // Token se pasa explícitamente para evitar importar apiClient (ciclo ESM)
  await authAxios.post('/users/change-password', payload, {
    headers: { Authorization: `Bearer ${token}` },
  })
}
