import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth.store'
import { changePasswordApi } from '@/api/auth'

export function ForcePasswordChange() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const navigate = useNavigate()

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function validate(): string | null {
    if (newPassword.length < 12) {
      return 'La nueva contraseña debe tener al menos 12 caracteres.'
    }
    if (newPassword !== confirmPassword) {
      return 'Las contraseñas no coinciden.'
    }
    return null
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    if (!accessToken) {
      setError('No hay sesión activa. Iniciá sesión nuevamente.')
      return
    }

    setIsSubmitting(true)
    try {
      await changePasswordApi({ new_password: newPassword }, accessToken)
      // Refresh para obtener token sin scope restrictivo
      await refreshToken()
      navigate('/', { replace: true })
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail as string | undefined
        setError(detail ?? 'Error al cambiar la contraseña. Intentá de nuevo.')
      } else {
        setError('Error de conexión. Verificá tu red.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="bg-gray-800 rounded-xl shadow-sm border border-gray-700 p-8">
      <div className="mb-8 text-center">
        <h1 className="text-xl font-bold text-white">Cambio de contraseña requerido</h1>
        <p className="mt-2 text-sm text-gray-500">
          Tu contraseña debe actualizarse antes de continuar. Elegí una contraseña de al menos
          12 caracteres.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <div>
          <label
            htmlFor="new_password"
            className="block text-sm font-medium text-gray-300 mb-1.5"
          >
            Nueva contraseña
          </label>
          <input
            id="new_password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            autoComplete="new-password"
            autoFocus
            minLength={12}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isSubmitting}
          />
          {newPassword && newPassword.length < 12 && (
            <p className="mt-1 text-xs text-red-400">
              {newPassword.length}/12 caracteres mínimos
            </p>
          )}
        </div>

        <div>
          <label
            htmlFor="confirm_password"
            className="block text-sm font-medium text-gray-300 mb-1.5"
          >
            Confirmar contraseña
          </label>
          <input
            id="confirm_password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            autoComplete="new-password"
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isSubmitting}
          />
          {confirmPassword && newPassword !== confirmPassword && (
            <p className="mt-1 text-xs text-red-400">Las contraseñas no coinciden.</p>
          )}
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
          disabled={isSubmitting || newPassword.length < 12 || newPassword !== confirmPassword}
          className="w-full py-2.5 px-4 bg-primary text-white text-sm font-medium rounded-md hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Guardando...
            </>
          ) : (
            'Cambiar contraseña'
          )}
        </button>
      </form>
    </div>
  )
}
