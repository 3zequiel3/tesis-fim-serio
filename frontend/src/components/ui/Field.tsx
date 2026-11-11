import type { ReactNode } from 'react'

export const inputClassName =
  'w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-text placeholder:text-text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-60'

interface FieldProps {
  id: string
  label: string
  hint?: string
  error?: string | null
  children: ReactNode
}

/** Label + control + optional hint/error, wired for assistive tech. */
export function Field({ id, label, hint, error, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block font-semibold text-text">
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-text-muted">{hint}</p>}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger-fg">
          {error}
        </p>
      )}
    </div>
  )
}
