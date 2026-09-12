import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getRules, getRulesetVersion, createRule, updateRule, deleteRule } from '@/api/rules'
import type { CreateRulePayload, UpdateRulePayload } from '@/api/rules'

const RULES_KEY = ['rules'] as const
const RULESET_VERSION_KEY = ['rules', 'version'] as const

export function useRules() {
  return useQuery({
    queryKey: RULES_KEY,
    queryFn: getRules,
  })
}

/** US-14 criterio 4 (C11): ruleset_version actual del sistema. */
export function useRulesetVersion() {
  return useQuery({
    queryKey: RULESET_VERSION_KEY,
    queryFn: getRulesetVersion,
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateRulePayload) => createRule(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY })
      qc.invalidateQueries({ queryKey: RULESET_VERSION_KEY })
    },
  })
}

export function useUpdateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UpdateRulePayload }) =>
      updateRule(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY })
      qc.invalidateQueries({ queryKey: RULESET_VERSION_KEY })
    },
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteRule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY })
      qc.invalidateQueries({ queryKey: RULESET_VERSION_KEY })
    },
  })
}
