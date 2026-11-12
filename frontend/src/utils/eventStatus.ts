import type { EventStatus } from '@/api/events'

/** The seven canonical event states of RN-71, in the order the console lists them. */
export const EVENT_STATUS_VALUES: readonly EventStatus[] = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
  'superseded',
]

/**
 * The name each state goes by on screen, for the person reading it.
 *
 * The canonical value is never replaced by this name: every surface that
 * shows a state renders both, the name to be read and the value to be
 * recognised. US-04's second criterion asks that the state values be shown in
 * lowercase snake_case, and C1 scopes the canonical lexicon to acceptance
 * criteria, example data and mockups — neither asks that the value be the only
 * thing on screen, and RN-71 governs persistence, APIs, streams, logs and
 * technical documentation rather than a label.
 */
export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  pending: 'Pendientes',
  approved: 'Aprobados',
  rejected: 'Rechazados',
  auto_restored: 'Restaurados',
  quarantined: 'En cuarentena',
  alert_only: 'Solo alerta',
  superseded: 'Reemplazados',
}

/** Singular form, for a badge that names one event rather than a count. */
export const EVENT_STATUS_LABELS_ONE: Record<EventStatus, string> = {
  pending: 'Pendiente',
  approved: 'Aprobado',
  rejected: 'Rechazado',
  auto_restored: 'Restaurado',
  quarantined: 'En cuarentena',
  alert_only: 'Solo alerta',
  superseded: 'Reemplazado',
}
