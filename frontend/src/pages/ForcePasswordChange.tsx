import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth.store'
import { changePasswordApi } from '@/api/auth'

const UPPERCASE_RE = /\p{Lu}/u
const LOWERCASE_RE = /\p{Ll}/u
const DIGIT_RE = /\p{Nd}/u

export function ForcePasswordChange() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const navigate = useNavigate()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function validate(): string | null {
    if (!currentPassword) {
      return 'Ingresá tu contraseña actual.'
    }
    if (newPassword.length < 12) {
      return 'La nueva contraseña debe tener al menos 12 caracteres.'
    }
    if (!UPPERCASE_RE.test(newPassword)) {
      return 'La nueva contraseña debe tener al menos una mayúscula.'
    }
    if (!LOWERCASE_RE.test(newPassword)) {
      return 'La nueva contraseña debe tener al menos una minúscula.'
    }
    if (!DIGIT_RE.test(newPassword)) {
      return 'La nueva contraseña debe tener al menos un número.'
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
      await changePasswordApi(
        { current_password: currentPassword, new_password: newPassword },
        accessToken,
      )
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
          Tu contraseña debe actualizarse antes de continuar. Elegí una contraseña que cumpla
          los requisitos.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <div>
          <label
            htmlFor="current_password"
            className="block text-sm font-medium text-gray-300 mb-1.5"
          >
            Contraseña actual
          </label>
          <input
            id="current_password"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            autoComplete="current-password"
            autoFocus
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isSubmitting}
          />
        </div>

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
            minLength={12}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-md text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-60"
            disabled={isSubmitting}
          />
          <ul className="mt-1.5 text-xs text-gray-500 space-y-0.5">
            <li className={newPassword.length >= 12 ? 'text-green-500' : undefined}>
              Mínimo 12 caracteres
            </li>
            <li className={UPPERCASE_RE.test(newPassword) ? 'text-green-500' : undefined}>
              Al menos 1 mayúscula
            </li>
            <li className={LOWERCASE_RE.test(newPassword) ? 'text-green-500' : undefined}>
              Al menos 1 minúscula
            </li>
            <li className={DIGIT_RE.test(newPassword) ? 'text-green-500' : undefined}>
              Al menos 1 número
            </li>
          </ul>
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
          disabled={isSubmitting}
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
