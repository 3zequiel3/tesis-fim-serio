import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Circle } from 'lucide-react'
import { changePasswordApi } from '@/api/auth'
import { apiErrorMessage } from '@/api/errors'
import { Button } from '@/components/ui/Button'
import { Field, inputClassName } from '@/components/ui/Field'
import { PASSWORD_CHANGED_NOTICE, useAuthStore } from '@/stores/auth.store'

const UPPERCASE_RE = /\p{Lu}/u
const LOWERCASE_RE = /\p{Ll}/u
const DIGIT_RE = /\p{Nd}/u

function Requirement({ met, children }: { met: boolean; children: string }) {
  return (
    <li className={`flex items-center gap-2 ${met ? 'text-success-fg' : 'text-text-muted'}`}>
      {met ? <Check aria-hidden="true" size={14} /> : <Circle aria-hidden="true" size={14} />}
      {children}
      <span className="sr-only">{met ? ' (cumplido)' : ' (pendiente)'}</span>
    </li>
  )
}

export function ForcePasswordChange() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const endSession = useAuthStore((s) => s.endSession)
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
    if (newPassword === currentPassword) {
      return 'La nueva contraseña debe ser distinta de la actual.'
    }
    if (newPassword !== confirmPassword) {
      return 'Las contraseñas no coinciden.'
    }
    return null
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (isSubmitting) return
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
    } catch (err) {
      setError(apiErrorMessage(err, 'Error al cambiar la contraseña. Intentá de nuevo.'))
      setIsSubmitting(false)
      return
    }
    // D89/RN-183: the backend already revoked every token of this user, so
    // there is nothing to refresh. End the local session and ask for a new login.
    endSession('password_changed')
    navigate('/login', { replace: true, state: { notice: PASSWORD_CHANGED_NOTICE } })
  }

  return (
    <div className="rounded-panel border border-line bg-surface-raised p-8">
      <h1 className="text-xl font-semibold text-text">Cambio de contraseña requerido</h1>
      <p className="mb-6 mt-2 text-text-muted">
        Tu contraseña debe actualizarse antes de continuar. Elegí una contraseña que cumpla los
        requisitos.
      </p>

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <Field id="current_password" label="Contraseña actual">
          <input
            id="current_password"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            autoComplete="current-password"
            autoFocus
            className={inputClassName}
            disabled={isSubmitting}
          />
        </Field>

        <div>
          <Field id="new_password" label="Nueva contraseña">
            <input
              id="new_password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              autoComplete="new-password"
              minLength={12}
              className={inputClassName}
              disabled={isSubmitting}
            />
          </Field>
          <ul className="mt-2 space-y-0.5 text-xs">
            <Requirement met={newPassword.length >= 12}>Mínimo 12 caracteres</Requirement>
            <Requirement met={UPPERCASE_RE.test(newPassword)}>Al menos 1 mayúscula</Requirement>
            <Requirement met={LOWERCASE_RE.test(newPassword)}>Al menos 1 minúscula</Requirement>
            <Requirement met={DIGIT_RE.test(newPassword)}>Al menos 1 número</Requirement>
          </ul>
        </div>

        <Field
          id="confirm_password"
          label="Confirmar contraseña"
          error={confirmPassword && newPassword !== confirmPassword ? 'Las contraseñas no coinciden.' : null}
        >
          <input
            id="confirm_password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            autoComplete="new-password"
            className={inputClassName}
            disabled={isSubmitting}
          />
        </Field>

        {error && (
          <div
            role="alert"
            className="rounded-control border border-danger-line bg-danger-bg px-3 py-2 text-danger-fg"
          >
            {error}
          </div>
        )}

        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>
          {isSubmitting ? 'Guardando...' : 'Cambiar contraseña'}
        </Button>
      </form>
    </div>
  )
}
