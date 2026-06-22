import { apiClient } from '@/api/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export type RuleSeverity = 'critical' | 'high' | 'medium' | 'low'
export type RuleAction = 'auto_restore' | 'quarantine' | 'manual_review' | 'alert_only'

export interface Rule {
  id: number
  pattern: string
  severity: RuleSeverity
  action: RuleAction
  ruleset_version: number
  created_at: string
  updated_at: string
}

export interface CreateRulePayload {
  pattern: string
  severity: RuleSeverity
  action: RuleAction
}

export interface UpdateRulePayload {
  pattern?: string
  severity?: RuleSeverity
  action?: RuleAction
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function getRules(): Promise<Rule[]> {
  const { data } = await apiClient.get<Rule[]>('/rules')
  return data
}

export async function createRule(payload: CreateRulePayload): Promise<Rule> {
  const { data } = await apiClient.post<Rule>('/rules', payload)
  return data
}

export async function updateRule(id: number, payload: UpdateRulePayload): Promise<Rule> {
  const { data } = await apiClient.put<Rule>(`/rules/${id}`, payload)
  return data
}

export async function deleteRule(id: number): Promise<void> {
  await apiClient.delete(`/rules/${id}`)
}
