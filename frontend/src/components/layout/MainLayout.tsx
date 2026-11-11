import { Suspense, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { DataState } from '@/components/ui/DataState'
import { useAlertsSSE } from '@/hooks/useAlertsSSE'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { AlertsBanner } from './AlertsBanner'
import { MobileNav, Sidebar } from './Sidebar'
import { Navbar } from './Navbar'
import { SystemBanner } from './SystemBanner'

const SIDEBAR_KEY = 'fim.sidebar'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === 'collapsed'
  } catch {
    return false
  }
}

export function MainLayout() {
  // Montaje único del feed SSE de alertas — app-wide, una sola conexión (C35 / FIX-02).
  useAlertsSSE()

  // > 768 px: sidebar (collapsible). ≤ 768 px: menu button + side panel.
  const isDesktop = useMediaQuery('(min-width: 769px)')
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [menuOpen, setMenuOpen] = useState(false)

  function toggleCollapsed() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, c ? 'expanded' : 'collapsed')
      } catch {
        // Storage may be blocked; the choice then lasts for this page load only.
      }
      return !c
    })
  }

  return (
    <div className="flex min-h-screen bg-surface">
      {isDesktop && <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <Navbar onOpenMenu={isDesktop ? undefined : () => setMenuOpen(true)} />
        <SystemBanner />
        <AlertsBanner />
        <main className="mx-auto w-full min-w-0 max-w-[1280px] flex-1 p-4 sm:p-6">
          {/* Inside the layout so the sidebar does not flicker while a page chunk loads. */}
          <Suspense fallback={<DataState isLoading loadingLabel="Cargando página…">{null}</DataState>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      {!isDesktop && menuOpen && <MobileNav onClose={() => setMenuOpen(false)} />}
    </div>
  )
}
