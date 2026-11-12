/**
 * El nombre que lleva en pantalla cada acción de regla.
 *
 * Estaba duplicado literal en `pages/Rules.tsx` y en
 * `components/ui/RuleForm.tsx`, y ausente de `pages/Alerts.tsx`, que
 * mostraba el valor crudo. Mismo contrato que `getSeverityMeta`: un Record
 * privado y un accesor que tolera lo desconocido.
 */
const RULE_ACTION_LABELS: Record<string, string> = {
  auto_restore: 'Auto-restaurar',
  quarantine: 'Cuarentena',
  manual_review: 'Revisión manual',
  alert_only: 'Solo alerta',
}

/** El nombre de la acción, o `undefined` si no es una de las cuatro conocidas. */
export function getRuleActionLabel(action: string | null | undefined): string | undefined {
  if (!action) return undefined
  return RULE_ACTION_LABELS[action]
}

/** Las cuatro acciones con su nombre, en el orden en que las ofrece el formulario. */
export const RULE_ACTION_OPTIONS = [
  { value: 'auto_restore', label: RULE_ACTION_LABELS.auto_restore },
  { value: 'quarantine', label: RULE_ACTION_LABELS.quarantine },
  { value: 'manual_review', label: RULE_ACTION_LABELS.manual_review },
  { value: 'alert_only', label: RULE_ACTION_LABELS.alert_only },
] as const
