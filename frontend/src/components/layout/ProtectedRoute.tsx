import { useEffect, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'

function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    return JSON.parse(atob(token.split('.')[1])) as Record<string, unknown>
  } catch {
    return {}
  }
}

export function ProtectedRoute() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()
  const location = useLocation()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    if (!accessToken) {
      refreshToken()
        .catch(() => undefined)
        .finally(() => {
          setChecked(true)
        })
    } else {
      setChecked(true)
    }
    // Solo ejecutar al montar
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // También cubre la pérdida de sesión DESPUÉS del montaje (por ejemplo, un
  // refresh anticipado o reactivo rechazado). El guard navega; el store sólo
  // administra credenciales y no necesita conocer el router.
  useEffect(() => {
    if (checked && !isLoading && !accessToken) {
      navigate('/login', { state: { from: location }, replace: true })
    }
  }, [accessToken, checked, isLoading, location, navigate])

  // Verificación de scope password_change_only (RN-100, D-FE-6)
  useEffect(() => {
    if (!accessToken || !checked) return

    const payload = decodeJwtPayload(accessToken)
    const scope = payload['scope'] as string | undefined

    if (scope === 'password_change_only' && location.pathname !== '/change-password') {
      navigate('/change-password', { replace: true })
    }
  }, [accessToken, checked, location.pathname, navigate])

  if (!checked || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Verificando sesión...</span>
        </div>
      </div>
    )
  }

  if (!accessToken) return null

  return <Outlet />
}
