import { Link2, Lock, Unlock, Trash2, TriangleAlert, Terminal, WifiOff } from 'lucide-react'
import type { CommandAckStatus, QuarantineState } from '@/api/events'
import { getAckStatusMeta } from '@/utils/ackStatus'
import { getQuarantineStateMeta } from '@/utils/quarantineState'
import { getActionFailedMeta } from '@/utils/actionFailed'

// Secondary indicators shared by the events table, the detail and the chain.
// None of them is an event state (RN-72): they qualify the primary StatusBadge.

const BASE = 'inline-flex shrink-0 items-center gap-1 rounded-control px-2 py-0.5 text-xs font-semibold'

const QUARANTINE_ICONS = { quarantined: Lock, released: Unlock, discarded: Trash2 } as const

/** Result of the quarantine (D82/RN-176). Omitted for `none`, absent or unknown. */
export function QuarantineStateBadge({ state }: { state?: QuarantineState | null }) {
  const meta = getQuarantineStateMeta(state)
  if (!meta || !state || state === 'none') return null
  const Icon = QUARANTINE_ICONS[state]
  return (
    <span data-testid="quarantine-state-badge" className={`${BASE} ${meta.className}`}>
      <Icon aria-hidden="true" size={12} />
      {meta.label}
    </span>
  )
}

/** Failed automatic remediation (D35/RN-129). Omitted when `action_failed` is false. */
export function ActionFailedBadge({ actionFailed }: { actionFailed: boolean }) {
  const meta = getActionFailedMeta(actionFailed)
  if (!meta) return null
  return (
    <span className={`${BASE} ${meta.className}`}>
      <TriangleAlert aria-hidden="true" size={12} />
      {meta.label}
    </span>
  )
}

/** Execution status of the last command (D30/RN-124). `variant="text"` shows the table's bare value. */
export function AckStatusBadge({
  ackStatus,
  variant = 'label',
}: {
  ackStatus?: CommandAckStatus | null
  variant?: 'label' | 'value'
}) {
  const meta = getAckStatusMeta(ackStatus)
  if (!meta) return null
  return (
    <span className={`${BASE} ${meta.className}`}>
      <Terminal aria-hidden="true" size={12} />
      {variant === 'value' ? ackStatus : meta.label}
    </span>
  )
}

export function SymlinkBadge({ isSymlink, target }: { isSymlink: boolean; target?: string | null }) {
  if (!isSymlink) return null
  return (
    <span
      title={target ? `Symlink -> ${target}` : undefined}
      className={`${BASE} border border-info-line bg-info-bg text-info-fg`}
    >
      <Link2 aria-hidden="true" size={12} />
      symlink
    </span>
  )
}

/** Changes found by the agent's start-up reconcile (D80/RN-174). Rendered only for `true`. */
export function OfflineDetectionBadge({ detectedOffline }: { detectedOffline?: boolean | null }) {
  if (detectedOffline !== true) return null
  return (
    <span
      className={`${BASE} border border-info-line bg-info-bg text-info-fg`}
      title="El cambio ocurrió con el agente detenido. La fecha de detección es el instante en que el agente lo detectó al arrancar, no cuando ocurrió."
    >
      <WifiOff aria-hidden="true" size={12} />
      detectado offline
    </span>
  )
}
