import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Login } from '@/pages/Login'
import { ForcePasswordChange } from '@/pages/ForcePasswordChange'
import { Events } from '@/pages/Events'
import { EventDetail } from '@/pages/EventDetail'
import { Rules } from '@/pages/Rules'
import { Agents } from '@/pages/Agents'
import { Dashboard } from '@/pages/Dashboard'
import { Alerts } from '@/pages/Alerts'
import { FailedAlerts } from '@/pages/FailedAlerts'

export function App() {
  return (
    <>
    <Toaster position="top-right" richColors />
    <BrowserRouter>
      <Routes>
        {/* Rutas públicas (auth) */}
        <Route
          path="/login"
          element={
            <AuthLayout>
              <Login />
            </AuthLayout>
          }
        />
        <Route
          path="/change-password"
          element={
            <AuthLayout>
              <ForcePasswordChange />
            </AuthLayout>
          }
        />

        {/* Rutas protegidas */}
        <Route element={<ProtectedRoute />}>
          <Route element={<MainLayout />}>
            {/* Redirige / → /dashboard (C19) */}
            <Route index element={<Navigate to="/dashboard" replace />} />

            {/* Dashboard — página por defecto post-login */}
            <Route path="/dashboard" element={<Dashboard />} />

            {/* Página de eventos (C18) */}
            <Route path="/events" element={<Events />} />
            <Route path="/events/:id" element={<EventDetail />} />

            {/* Reglas (C19) */}
            <Route path="/rules" element={<Rules />} />

            {/* Agentes (C19) */}
            <Route path="/agents" element={<Agents />} />

            {/* Alertas (C19) */}
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/alerts/failed" element={<FailedAlerts />} />

            <Route
              path="*"
              element={
                <div className="text-center py-16 text-gray-500">
                  Página no encontrada
                </div>
              }
            />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
    </>
  )
}
