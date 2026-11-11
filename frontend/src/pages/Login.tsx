import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Info } from 'lucide-react'
import { readApiError } from '@/api/errors'
import { Button } from '@/components/ui/Button'
import { Field, inputClassName } from '@/components/ui/Field'
import { useAuthStore } from '@/stores/auth.store'
import { postLoginTarget } from '@/utils/safeRedirect'

const INVALID_CREDENTIALS = 'Credenciales incorrectas. Revisá tu usuario y contraseña.'

function formatWait(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds} ${totalSeconds === 1 ? 'segundo' : 'segundos'}`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const m = `${minutes} ${minutes === 1 ? 'minuto' : 'minutos'}`
  return seconds === 0 ? m : `${m} y ${seconds} s`
}

export function Login() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const login = useAuthStore((s) => s.login)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { from?: unknown; notice?: unknown } | null
  const notice = typeof state?.notice === 'string' ? state.notice : null

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  // 429: epoch ms until which submitting stays disabled (RN-88, D92/RN-186).
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (blockedUntil === null) return
    const id = setInterval(() => {
      const t = Date.now()
      setNow(t)
      if (t >= blockedUntil) {
        setBlockedUntil(null)
        setError(null)
      }
    }, 1000)
    return () => clearInterval(id)
  }, [blockedUntil])

  // Si ya hay sesión activa, redirigir al dashboard
  if (accessToken) {
    return <Navigate to="/" replace />
  }

  const remainingSeconds = blockedUntil === null ? 0 : Math.max(0, Math.ceil((blockedUntil - now) / 1000))
  const blocked = remainingSeconds > 0

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (blocked) return
    setError(null)

    try {
      await login({ username, password })
      void navigate(postLoginTarget(state?.from), { replace: true })
    } catch (err) {
      const apiError = readApiError(err)
      if (apiError.status === 429) {
        const wait = apiError.retryAfter
        if (wait && wait > 0) {
          setNow(Date.now())
          setBlockedUntil(Date.now() + wait * 1000)
          setError(
            `Demasiados intentos fallidos: superaste el límite permitido. Podés reintentar en ${formatWait(wait)}.`,
          )
        } else {
          setError('Demasiados intentos fallidos. Esperá unos minutos antes de reintentar.')
        }
      } else if (apiError.status === 401) {
        // A legacy backend sends an English string here: keep the Spanish default then.
        setError(apiError.code && apiError.message ? apiError.message : INVALID_CREDENTIALS)
      } else if (apiError.status === 0) {
        setError(apiError.message)
      } else {
        setError(apiError.message || 'Error inesperado. Intentá de nuevo más tarde.')
      }
    }
  }

  const waitLeft = blocked ? formatWait(remainingSeconds) : null

  return (
    <div className="rounded-panel border border-line bg-surface-raised p-8">
      <h1 className="text-2xl font-semibold text-text">Iniciá sesión</h1>
      <p className="mb-6 mt-1 text-text-muted">Ingresá con tu usuario para ver el estado de la integridad.</p>

      {notice && (
        <div
          role="status"
          className="mb-5 flex items-start gap-2 rounded-control border border-info-line bg-info-bg px-3 py-2 text-info-fg"
        >
          <Info aria-hidden="true" size={18} className="mt-0.5 shrink-0" />
          <span>{notice}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <Field id="username" label="Usuario">
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoComplete="username"
            autoFocus
            className={inputClassName}
            disabled={isLoading}
          />
        </Field>

        <Field id="password" label="Contraseña">
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            className={inputClassName}
            disabled={isLoading}
          />
        </Field>

        {error && (
          <div
            role="alert"
            className="rounded-control border border-danger-line bg-danger-bg px-3 py-2 text-danger-fg"
          >
            {error}
            {waitLeft && <span className="sr-only"> Tiempo restante: {waitLeft}.</span>}
          </div>
        )}

        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={isLoading}
          disabled={blocked || !username || !password}
        >
          {isLoading ? 'Ingresando...' : blocked ? `Reintentar en ${waitLeft}` : 'Ingresar'}
        </Button>
      </form>
    </div>
  )
}
