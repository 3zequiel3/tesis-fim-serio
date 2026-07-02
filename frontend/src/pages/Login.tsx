import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth.store'

export function Login() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const login = useAuthStore((s) => s.login)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Si ya hay sesión activa, redirigir al dashboard
  if (accessToken) {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)

    try {
      await login({ username, password })
      navigate('/', { replace: true })
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 401) {
          setError('Credenciales incorrectas. Revisá tu usuario y contraseña.')
        } else if (err.response?.status === 429) {
          setError(
            'Demasiados intentos. Esperá unos minutos antes de reintentar.',
          )
        } else {
          setError('Error inesperado. Intentá de nuevo más tarde.')
        }
      } else {
        setError('Error de conexión. Verificá tu red.')
      }
    }
  }

  return (
    <div className="bg-gray-800 rounded-xl shadow-sm border border-gray-700 p-8">
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-bold text-white">FIM Platform</h1>
        <p className="mt-1 text-sm text-gray-500">Iniciá sesión para continuar</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <div>
          <label
            htmlFor="username"
            className="block text-sm font-medium text-gray-300 mb-1.5"
          >
            Usuario
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoComplete="username"
            autoFocus
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isLoading}
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-gray-300 mb-1.5"
          >
            Contraseña
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isLoading}
          />
        </div>

        {error && (
          <div
            role="alert"
            className="text-sm text-red-300 bg-red-950 border border-red-800 rounded-md px-3 py-2"
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={isLoading || !username || !password}
          className="w-full py-2.5 px-4 bg-primary text-white text-sm font-medium rounded-md hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Ingresando...
            </>
          ) : (
            'Ingresar'
          )}
        </button>
      </form>
    </div>
  )
}
