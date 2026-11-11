import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const next = theme === 'dark' ? 'claro' : 'oscuro'
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Cambiar a tema ${next}`}
      title={`Cambiar a tema ${next}`}
      className="inline-flex size-9 items-center justify-center rounded-control border border-line text-text-muted hover:bg-surface-hover hover:text-text"
    >
      {theme === 'dark' ? <Sun aria-hidden="true" size={18} /> : <Moon aria-hidden="true" size={18} />}
    </button>
  )
}
