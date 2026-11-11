import { LogOut, Menu } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { useCan } from '@/hooks/useCan'
import { useAuthStore } from '@/stores/auth.store'

export const READ_ONLY_LEGEND = 'Modo lectura: tu usuario no puede modificar la configuración.'

interface NavbarProps {
  /** Present on narrow screens (≤ 768 px): shows the menu button. */
  onOpenMenu?: () => void
}

export function Navbar({ onOpenMenu }: NavbarProps) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const canMutate = useCan()

  async function handleLogout() {
    const revoked = await logout()
    if (!revoked) {
      toast.error('La sesión local se cerró, pero no se pudo confirmar la revocación en el servidor')
    }
    navigate('/login', { replace: true })
  }

  return (
    <header className="sticky top-0 z-20 flex min-h-14 items-center gap-3 border-b border-line bg-surface-raised px-4 py-2 sm:px-6">
      {onOpenMenu && (
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label="Abrir menú de navegación"
          className="inline-flex size-9 shrink-0 items-center justify-center rounded-control border border-line text-text-muted hover:bg-surface-hover hover:text-text"
        >
          <Menu aria-hidden="true" size={18} />
        </button>
      )}
      <div className="min-w-0 flex-1">
        {user && !canMutate && (
          <p role="note" className="truncate rounded-control bg-info-bg px-2.5 py-1 text-xs font-semibold text-info-fg">
            {READ_ONLY_LEGEND}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        <ThemeToggle />
        {user && <span className="hidden font-semibold text-text sm:inline">{user.username}</span>}
        <button
          onClick={handleLogout}
          aria-label="Cerrar sesión"
          className="inline-flex items-center gap-2 rounded-control border border-line-strong px-3 py-1.5 text-text hover:bg-surface-hover"
          type="button"
        >
          <LogOut aria-hidden="true" size={16} />
          <span className="hidden sm:inline">Cerrar sesión</span>
        </button>
      </div>
    </header>
  )
}
