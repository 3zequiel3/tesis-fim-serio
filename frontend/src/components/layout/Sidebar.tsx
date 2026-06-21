import { NavLink } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { to: '/events', label: 'Eventos', icon: '📋' },
  { to: '/rules', label: 'Reglas', icon: '🛡️' },
  { to: '/agents', label: 'Agentes', icon: '🤖' },
  { to: '/dashboard', label: 'Dashboard', icon: '📊' },
  { to: '/alerts', label: 'Alertas', icon: '🔔' },
]

export function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-gray-900 text-gray-100 flex flex-col">
      <div className="px-4 py-5 border-b border-gray-700">
        <span className="text-lg font-semibold tracking-tight">FIM Platform</span>
      </div>
      <nav className="flex-1 py-4">
        <ul className="space-y-1 px-2">
          {navItems.map(({ to, label, icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary text-white'
                      : 'text-gray-300 hover:bg-gray-700 hover:text-white',
                  ].join(' ')
                }
              >
                <span aria-hidden="true">{icon}</span>
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  )
}
