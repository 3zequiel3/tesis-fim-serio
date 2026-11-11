import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore, SESSION_EXPIRED_NOTICE } from '@/stores/auth.store'

function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const encoded = token.split('.')[1] ?? ''
    // JWTs are base64url; atob only reads the standard alphabet.
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64)) as Record<string, unknown>
  } catch {
    return {}
  }
}

export function ProtectedRoute() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const endedReason = useAuthStore((s) => s.endedReason)
  const clearEndedReason = useAuthStore((s) => s.clearEndedReason)
  const navigate = useNavigate()
  const location = useLocation()
  // Only the INITIAL verification (silent refresh on mount) shows the loading
  // screen. A later renewal never touches this flag, so it cannot unmount the
  // routes and lose modals, selection or filters (B4, design D-5).
  const [checked, setChecked] = useState(() => Boolean(accessToken))

  useEffect(() => {
    if (accessToken) return
    let active = true
    void refreshToken()
      .catch(() => undefined)
      .finally(() => {
        if (active) setChecked(true)
      })
    return () => {
      active = false
    }
    // Only on mount: later token changes are handled by the redirect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Also covers losing the session AFTER mount (a failed renewal, a 401 that
  // could not refresh, logout from another place): go to login with the notice.
  useEffect(() => {
    if (checked && !accessToken) {
      const notice = endedReason === 'expired' ? SESSION_EXPIRED_NOTICE : undefined
      clearEndedReason()
      void navigate('/login', { state: { from: location, notice }, replace: true })
    }
  }, [accessToken, checked, endedReason, clearEndedReason, location, navigate])

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <div role="status" className="flex flex-col items-center gap-3 text-text-muted">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <span>Verificando sesión...</span>
        </div>
      </div>
    )
  }

  if (!accessToken) return null

  // RN-100, design D-6: decided while rendering, so no child page ever mounts
  // (and no query is ever sent) with a password_change_only token (D16).
  const scope = decodeJwtPayload(accessToken)['scope']
  if (scope === 'password_change_only' && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }

  return <Outlet />
}
