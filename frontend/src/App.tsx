import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Login } from '@/pages/Login'
import { ForcePasswordChange } from '@/pages/ForcePasswordChange'
import { Events } from '@/pages/Events'
import { EventDetail } from '@/pages/EventDetail'

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
            {/* Redirige / → /events (C18 agrega la página real) */}
            <Route index element={<Navigate to="/events" replace />} />

            {/* Página de eventos (C18) */}
            <Route path="/events" element={<Events />} />
            <Route path="/events/:id" element={<EventDetail />} />

            {/* Placeholders para C19 */}
            <Route
              path="/rules"
              element={<PlaceholderPage title="Reglas" />}
            />
            <Route
              path="/agents"
              element={<PlaceholderPage title="Agentes" />}
            />
            <Route
              path="/dashboard"
              element={<PlaceholderPage title="Dashboard" />}
            />
            <Route
              path="/alerts"
              element={<PlaceholderPage title="Alertas" />}
            />

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

function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="text-center py-16 text-gray-400">
      <p className="text-2xl font-semibold text-gray-300">{title}</p>
      <p className="mt-2 text-sm">Esta sección se implementa en C18 / C19.</p>
    </div>
  )
}
