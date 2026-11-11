import { lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Login } from '@/pages/Login'
import { ForcePasswordChange } from '@/pages/ForcePasswordChange'

// Design D-12: every routed page except Login and ForcePasswordChange loads on
// demand, so the entry chunk stays small. MainLayout wraps the outlet in a
// Suspense, so the sidebar does not flicker while a page chunk loads.
const Events = lazy(() => import('@/pages/Events').then((m) => ({ default: m.Events })))
const EventDetail = lazy(() => import('@/pages/EventDetail').then((m) => ({ default: m.EventDetail })))
const EventChain = lazy(() => import('@/pages/EventChain').then((m) => ({ default: m.EventChain })))
const Rules = lazy(() => import('@/pages/Rules').then((m) => ({ default: m.Rules })))
const Agents = lazy(() => import('@/pages/Agents').then((m) => ({ default: m.Agents })))
const Dashboard = lazy(() => import('@/pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const Alerts = lazy(() => import('@/pages/Alerts').then((m) => ({ default: m.Alerts })))
const FailedAlerts = lazy(() => import('@/pages/FailedAlerts').then((m) => ({ default: m.FailedAlerts })))

export function App() {
  return (
    <>
      <Toaster position="top-right" richColors closeButton />
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
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/events" element={<Events />} />
              <Route path="/events/:id" element={<EventDetail />} />
              {/* Cadena de eventos del mismo path (US-10) */}
              <Route path="/events/:id/chain" element={<EventChain />} />
              <Route path="/rules" element={<Rules />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/alerts/failed" element={<FailedAlerts />} />
              <Route
                path="*"
                element={<div className="py-16 text-center text-text-muted">Página no encontrada</div>}
              />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </>
  )
}
