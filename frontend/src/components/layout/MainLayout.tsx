import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Navbar } from './Navbar'
import { SystemBanner } from './SystemBanner'
import { AlertsBanner } from './AlertsBanner'
import { useAlertsSSE } from '@/hooks/useAlertsSSE'

export function MainLayout() {
  // Montaje único del feed SSE de alertas — app-wide, una sola conexión (C35 / FIX-02).
  useAlertsSSE()

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <SystemBanner />
        <AlertsBanner />
        <Navbar />
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
