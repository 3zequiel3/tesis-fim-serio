import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent hover:bg-accent-hover border border-transparent',
  secondary: 'bg-surface-raised text-text border border-line-strong hover:bg-surface-hover',
  danger: 'bg-danger-solid text-on-danger hover:bg-danger-solid-hover border border-transparent',
  ghost: 'bg-transparent text-text-muted border border-transparent hover:bg-surface-hover hover:text-text',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  /** Shows a spinner and disables the button (the label stays for assistive tech). */
  loading?: boolean
  size?: 'sm' | 'md'
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  className = '',
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        'inline-flex items-center justify-center gap-2 rounded-control font-semibold transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-3 py-1 text-xs' : 'px-4 py-2 text-sm',
        VARIANTS[variant],
        className,
      ].join(' ')}
      {...rest}
    >
      {loading && <Loader2 aria-hidden="true" size={16} className="animate-spin" />}
      {children}
    </button>
  )
}
