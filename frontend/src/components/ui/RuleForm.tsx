import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { inputClassName } from '@/components/ui/Field'
import type { Rule, RuleSeverity, RuleAction, CreateRulePayload, UpdateRulePayload } from '@/api/rules'

interface RuleFormProps {
  /** Si se pasa una regla existente, el formulario está en modo edición */
  rule?: Rule
  onSubmit: (payload: CreateRulePayload | UpdateRulePayload) => void
  onCancel: () => void
  isLoading?: boolean
  /** Backend `pattern_*` rejection (D91/RN-185), shown next to the field. */
  patternServerError?: string | null
}

const SEVERITY_OPTIONS: { value: RuleSeverity; label: string }[] = [
  { value: 'critical', label: 'critical' },
  { value: 'high', label: 'high' },
  { value: 'medium', label: 'medium' },
  { value: 'low', label: 'low' },
]

const ACTION_OPTIONS: { value: RuleAction; label: string }[] = [
  { value: 'auto_restore', label: 'Auto-restaurar' },
  { value: 'quarantine', label: 'Cuarentena' },
  { value: 'manual_review', label: 'Revisión manual' },
  { value: 'alert_only', label: 'Solo alerta' },
]

export function RuleForm({ rule, onSubmit, onCancel, isLoading, patternServerError }: RuleFormProps) {
  const [pattern, setPattern] = useState(rule?.pattern ?? '')
  const [severity, setSeverity] = useState<RuleSeverity>(rule?.severity ?? 'medium')
  const [action, setAction] = useState<RuleAction>(rule?.action ?? 'alert_only')
  const [patternError, setPatternError] = useState<string | null>(null)

  function validate(): boolean {
    if (!pattern.trim()) {
      setPatternError('El patrón no puede estar vacío')
      return false
    }
    setPatternError(null)
    return true
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!validate()) return
    onSubmit({ pattern: pattern.trim(), severity, action })
  }

  const shownError = patternError ?? patternServerError ?? null

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="rule-pattern" className="mb-1 block font-semibold text-text">
          Patrón <span aria-hidden="true" className="text-danger-fg">*</span>
        </label>
        <input
          type="text"
          id="rule-pattern"
          value={pattern}
          onChange={(e) => {
            setPattern(e.target.value)
            if (patternError) setPatternError(null)
          }}
          placeholder="/etc/**"
          className={`${inputClassName} font-mono ${shownError ? '!border-danger-line' : ''}`}
          aria-invalid={shownError ? 'true' : 'false'}
          aria-describedby={shownError ? 'rule-pattern-error' : undefined}
        />
        {shownError && (
          <p id="rule-pattern-error" className="mt-1 text-xs text-danger-fg">{shownError}</p>
        )}
      </div>

      <div>
        <label htmlFor="rule-severity" className="mb-1 block font-semibold text-text">Severidad</label>
        <select
          id="rule-severity"
          value={severity}
          onChange={(e) => setSeverity(e.target.value as RuleSeverity)}
          className={inputClassName}
        >
          {SEVERITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="rule-action" className="mb-1 block font-semibold text-text">Acción</label>
        <select
          id="rule-action"
          value={action}
          onChange={(e) => setAction(e.target.value as RuleAction)}
          className={inputClassName}
        >
          {ACTION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-end gap-3 pt-2">
        <Button onClick={onCancel} disabled={isLoading}>
          Cancelar
        </Button>
        <Button type="submit" variant="primary" loading={isLoading}>
          {isLoading ? 'Guardando...' : rule ? 'Guardar cambios' : 'Crear regla'}
        </Button>
      </div>
    </form>
  )
}
