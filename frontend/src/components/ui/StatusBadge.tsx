import { ArrowRightLeft, Bell, Check, CircleHelp, Clock, Lock, RotateCcw, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { EventStatus } from '@/api/events'

// The only renderer of the seven RN-71 states (D93/RN-187): color + icon +
// canonical snake_case text, so state is never conveyed by color alone.
// Tailwind scans class names statically, so each state lists its full classes.

interface StatusStyle {
  Icon: LucideIcon
  className: string
}

// Typed by EventStatus: adding a state to RN-71 fails to compile until it has a style.
const STATUS_STYLES: Record<EventStatus, StatusStyle> = {
  pending: { Icon: Clock, className: 'bg-status-pending-bg text-status-pending-fg' },
  approved: { Icon: Check, className: 'bg-status-approved-bg text-status-approved-fg' },
  rejected: { Icon: X, className: 'bg-status-rejected-bg text-status-rejected-fg' },
  superseded: { Icon: ArrowRightLeft, className: 'bg-status-superseded-bg text-status-superseded-fg' },
  auto_restored: { Icon: RotateCcw, className: 'bg-status-auto_restored-bg text-status-auto_restored-fg' },
  quarantined: { Icon: Lock, className: 'bg-status-quarantined-bg text-status-quarantined-fg' },
  alert_only: { Icon: Bell, className: 'bg-status-alert_only-bg text-status-alert_only-fg' },
}

const UNKNOWN_STYLE: StatusStyle = { Icon: CircleHelp, className: 'bg-neutral-bg text-neutral-fg' }

export function StatusBadge({ status, className = '' }: { status: string; className?: string }) {
  const { Icon, className: tone } = (STATUS_STYLES as Record<string, StatusStyle>)[status] ?? UNKNOWN_STYLE
  return (
    <span
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 text-xs font-semibold ${tone} ${className}`}
    >
      <Icon aria-hidden="true" size={14} strokeWidth={2.25} />
      {status}
    </span>
  )
}
