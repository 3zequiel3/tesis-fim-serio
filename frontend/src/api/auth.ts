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

export interface AuthUser {
  id: number
  username: string
  role: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

export interface RefreshResponse {
  access_token: string
  token_type: string
  user?: AuthUser
}

export async function loginApi(credentials: LoginCredentials): Promise<LoginResponse> {
  const { data } = await authAxios.post<LoginResponse>('/auth/login', credentials)
  return data
}

export async function refreshApi(): Promise<RefreshResponse> {
  const { data } = await authAxios.post<RefreshResponse>('/auth/refresh')
  return data
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
