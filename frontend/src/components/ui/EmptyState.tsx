import type { ReactNode } from 'react'

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="rounded-panel border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="font-semibold text-text">{title}</p>
      {hint && <p className="mx-auto mt-1 max-w-prose text-text-muted">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
