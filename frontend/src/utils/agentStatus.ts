/**
 * Cómo se presenta el estado de un agente: nombre y tono.
 *
 * Estaba partido en dos: `pages/Dashboard.tsx` tenía los nombres en español
 * y `components/ui/AgentCard.tsx` los colores con el valor crudo al lado.
 * El resultado era que el mismo agente figuraba como «Caído» en el
 * dashboard y como `dead` en su tarjeta. Mismo contrato que
 * `getSeverityMeta`: un Record privado y un accesor que tolera lo
 * desconocido.
 */
export interface AgentStatusMeta {
  /** El nombre que lleva en pantalla. `undefined` para un estado desconocido. */
  label: string | undefined
  /** Clases del badge — verbatim de AgentCard.tsx:44-50. */
  toneClass: string
}

const NEUTRAL_META: AgentStatusMeta = { label: undefined, toneClass: 'bg-neutral-bg text-neutral-fg' }

const AGENT_STATUS_META: Record<string, AgentStatusMeta> = {
  online: { label: 'En línea', toneClass: 'bg-success-bg text-success-fg' },
  offline: { label: 'Sin conexión', toneClass: 'bg-neutral-bg text-neutral-fg' },
  draining: { label: 'Drenando', toneClass: 'bg-warning-bg text-warning-fg' },
  dead: { label: 'Caído', toneClass: 'bg-danger-bg text-danger-fg' },
  revoked: { label: 'Revocado', toneClass: 'bg-danger-bg text-danger-fg' },
}

export function getAgentStatusMeta(status: string | null | undefined): AgentStatusMeta {
  if (!status) return NEUTRAL_META
  return AGENT_STATUS_META[status] ?? NEUTRAL_META
}
