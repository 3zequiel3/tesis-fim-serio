import { Bell, BellRing, LayoutDashboard, PanelLeftClose, PanelLeftOpen, ShieldCheck, ListChecks, Server, ScrollText, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import { useDialogBehavior } from '@/hooks/useDialogBehavior'

interface NavItem {
  to: string
  label: string
  Icon: LucideIcon
  end?: boolean
}

interface NavGroup {
  title: string
  items: NavItem[]
}

// RN-187: Supervisión (Dashboard, Eventos, Alertas) and Configuración (Reglas, Agentes).
const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Supervisión',
    items: [
      { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
      { to: '/events', label: 'Eventos', Icon: ListChecks },
      { to: '/alerts', label: 'Alertas', Icon: Bell, end: true },
      { to: '/alerts/failed', label: 'Alertas fallidas', Icon: BellRing },
    ],
  },
  {
    title: 'Configuración',
    items: [
      { to: '/rules', label: 'Reglas', Icon: ScrollText },
      { to: '/agents', label: 'Agentes', Icon: Server },
    ],
  },
]

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav aria-label="Navegación principal" className="flex-1 overflow-y-auto py-3">
      {NAV_GROUPS.map((group) => (
        <div key={group.title} className="mb-4">
          {collapsed ? (
            <div className="mx-3 mb-1 border-t border-line first:hidden" aria-hidden="true" />
          ) : (
            <p className="px-4 pb-1 text-xs font-semibold text-text-muted">{group.title}</p>
          )}
          <ul className="space-y-0.5 px-2">
            {group.items.map(({ to, label, Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  onClick={onNavigate}
                  aria-label={collapsed ? label : undefined}
                  title={collapsed ? label : undefined}
                  className={({ isActive }) =>
                    [
                      'flex items-center gap-3 rounded-control px-3 py-2 font-medium transition-colors',
                      collapsed ? 'justify-center' : '',
                      isActive
                        ? 'bg-accent-soft text-accent-soft-text'
                        : 'text-text-muted hover:bg-surface-hover hover:text-text',
                    ].join(' ')
                  }
                >
                  <Icon aria-hidden="true" size={18} className="shrink-0" />
                  {!collapsed && <span className="truncate">{label}</span>}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={`flex h-14 items-center gap-2.5 border-b border-line px-4 ${collapsed ? 'justify-center' : ''}`}>
      <ShieldCheck aria-hidden="true" size={24} className="shrink-0 text-accent" />
      {!collapsed && <span className="truncate text-lg font-semibold text-text">FIM Platform</span>}
    </div>
  )
}

interface SidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
}

/** Desktop sidebar: 232 px, collapsible to a 64 px icon rail with accessible labels. */
export function Sidebar({ collapsed, onToggleCollapsed }: SidebarProps) {
  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-line bg-surface-raised ${collapsed ? 'w-16' : 'w-[232px]'}`}
    >
      <Brand collapsed={collapsed} />
      <NavList collapsed={collapsed} />
      <div className="border-t border-line p-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expandir menú lateral' : 'Contraer menú lateral'}
          aria-expanded={!collapsed}
          className={`flex w-full items-center gap-3 rounded-control px-3 py-2 text-text-muted hover:bg-surface-hover hover:text-text ${collapsed ? 'justify-center' : ''}`}
        >
          {collapsed ? (
            <PanelLeftOpen aria-hidden="true" size={18} />
          ) : (
            <>
              <PanelLeftClose aria-hidden="true" size={18} />
              <span>Contraer</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}

/** Mobile (≤ 768 px) navigation panel: focus trapped, closes with Escape or the backdrop. */
export function MobileNav({ onClose }: { onClose: () => void }) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const portalRef = useRef<HTMLDivElement>(null)
  const state = useDialogBehavior({ panelRef, portalRef, onClose })

  return createPortal(
    <div ref={portalRef} className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={() => state.current.onClose()} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="animate-enter relative flex h-full w-[260px] max-w-[85vw] flex-col border-r border-line bg-surface-raised shadow-modal focus:outline-none"
      >
        <div className="flex h-14 items-center justify-between gap-2 border-b border-line px-4">
          <span className="flex items-center gap-2.5">
            <ShieldCheck aria-hidden="true" size={24} className="text-accent" />
            <span id={titleId} className="text-lg font-semibold text-text">
              FIM Platform
            </span>
          </span>
          <button
            type="button"
            aria-label="Cerrar menú de navegación"
            onClick={onClose}
            className="rounded-control p-1 text-text-muted hover:bg-surface-hover hover:text-text"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </div>
        <NavList collapsed={false} onNavigate={onClose} />
      </div>
    </div>,
    document.body,
  )
}
