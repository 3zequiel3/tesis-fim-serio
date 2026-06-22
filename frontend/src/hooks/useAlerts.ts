import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAlerts, getFailedAlerts, retryAlert, discardAlert } from '@/api/alerts'
import type { AlertFilters } from '@/api/alerts'

export function useAlerts(filters: AlertFilters = {}) {
  return useQuery({
    queryKey: ['alerts', filters],
    queryFn: () => getAlerts(filters),
    placeholderData: (prev) => prev,
  })
}

export function useFailedAlerts() {
  return useQuery({
    queryKey: ['alerts', 'failed'],
    queryFn: getFailedAlerts,
  })
}

export function useRetryAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => retryAlert(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alerts', 'failed'] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}

export function useDiscardAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => discardAlert(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alerts', 'failed'] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}
