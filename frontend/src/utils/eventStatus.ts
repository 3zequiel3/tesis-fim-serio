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
