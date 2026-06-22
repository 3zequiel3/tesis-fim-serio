import { useState, useEffect } from 'react'
import type { Rule, RuleSeverity, RuleAction, CreateRulePayload, UpdateRulePayload } from '@/api/rules'

interface RuleFormProps {
  /** Si se pasa una regla existente, el formulario está en modo edición */
  rule?: Rule
  onSubmit: (payload: CreateRulePayload | UpdateRulePayload) => void
  onCancel: () => void
  isLoading?: boolean
}

const SEVERITY_OPTIONS: { value: RuleSeverity; label: string }[] = [
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

const ACTION_OPTIONS: { value: RuleAction; label: string }[] = [
  { value: 'auto_restore', label: 'Auto-restaurar' },
  { value: 'quarantine', label: 'Cuarentena' },
  { value: 'manual_review', label: 'Revisión manual' },
  { value: 'alert_only', label: 'Solo alerta' },
]

export function RuleForm({ rule, onSubmit, onCancel, isLoading }: RuleFormProps) {
  const [pattern, setPattern] = useState(rule?.pattern ?? '')
  const [severity, setSeverity] = useState<RuleSeverity>(rule?.severity ?? 'medium')
  const [action, setAction] = useState<RuleAction>(rule?.action ?? 'alert_only')
  const [patternError, setPatternError] = useState<string | null>(null)

  useEffect(() => {
    if (rule) {
      setPattern(rule.pattern)
      setSeverity(rule.severity)
      setAction(rule.action)
    }
  }, [rule])

  function validate(): boolean {
    if (!pattern.trim()) {
      setPatternError('El pattern no puede estar vacío')
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

  const inputCls =
    'w-full px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500'
  const selectCls =
    'w-full px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-blue-500'

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs text-gray-400 mb-1">
          Pattern <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={pattern}
          onChange={(e) => {
            setPattern(e.target.value)
            if (patternError) setPatternError(null)
          }}
          placeholder="/etc/**"
          className={`${inputCls} ${patternError ? 'border-red-500' : ''}`}
        />
        {patternError && (
          <p className="mt-1 text-xs text-red-400">{patternError}</p>
        )}
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Severidad</label>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as RuleSeverity)}
          className={selectCls}
        >
          {SEVERITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Acción</label>
        <select
          value={action}
          onChange={(e) => setAction(e.target.value as RuleAction)}
          className={selectCls}
        >
          {ACTION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isLoading}
          className="px-4 py-1.5 text-sm text-gray-300 hover:text-white disabled:opacity-40"
        >
          Cancelar
        </button>
        <button
          type="submit"
          disabled={isLoading}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded disabled:opacity-40"
        >
          {isLoading ? 'Guardando...' : rule ? 'Guardar cambios' : 'Crear regla'}
        </button>
      </div>
    </form>
  )
}
