import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import axios from 'axios'
import {
  approve,
  reject,
  bulkApprove,
  bulkReject,
  type ApproveParams,
  type RejectParams,
  type BulkItem,
  type BulkRejectItem,
} from '@/api/actions'

/**
 * Un 422 en una acción bulk es una violación de contrato — el cuerpo que el
 * cliente emitió no fue el que el backend acepta —, no una falla operativa
 * como un timeout o un 5xx. Presentarlos con el mismo texto genérico es lo
 * que mantuvo el bulk-reject roto en silencio toda la vida del proyecto
 * (D-5 del design de frontend-severity-triage).
 */
function bulkActionErrorMessage(err: unknown, verb: string): string | null {
  if (!axios.isAxiosError(err)) return null
  if (err.response?.status === 422) {
    return `Petición de ${verb} rechazada por el servidor (cuerpo inválido)`
  }
  return `Error al ${verb} en lote`
}

interface UseEventActionsOptions {
  /** event_id del evento individual (solo para acciones individuales) */
  eventId?: number
}

export function useEventActions({ eventId }: UseEventActionsOptions = {}) {
  const queryClient = useQueryClient()
  const [needsAbsentConfirmation, setNeedsAbsentConfirmation] = useState(false)

  function invalidateEvent() {
    if (eventId != null) {
      queryClient.invalidateQueries({ queryKey: ['event', eventId] })
    }
    queryClient.invalidateQueries({ queryKey: ['events'] })
  }

  function handleActionError(err: unknown) {
    if (!axios.isAxiosError(err)) return
    const status = err.response?.status
    if (status === 409) {
      toast.error('Este evento ya fue resuelto por otro admin')
      invalidateEvent()
      return
    }
    if (status === 422) {
      const data = err.response?.data as { code?: string } | undefined
      if (data?.code === 'absent_confirmation_required') {
        setNeedsAbsentConfirmation(true)
        return
      }
    }
    toast.error('Error al procesar la acción')
  }

  const approveMutation = useMutation({
    mutationFn: (params: ApproveParams) => approve(params),
    onError: handleActionError,
    onSuccess: () => {
      invalidateEvent()
      toast.success('Evento aprobado')
      setNeedsAbsentConfirmation(false)
    },
  })

  const rejectMutation = useMutation({
    mutationFn: (params: RejectParams) => reject(params),
    onError: handleActionError,
    onSuccess: () => {
      invalidateEvent()
      toast.success('Evento rechazado')
    },
  })

  const bulkApproveMutation = useMutation({
    mutationFn: (items: BulkItem[]) => bulkApprove(items),
    onError: (err: unknown) => {
      const message = bulkActionErrorMessage(err, 'aprobar')
      if (message) toast.error(message)
    },
    onSuccess: (result) => {
      const ok = result.succeeded.length
      const fail = result.failed.length
      if (fail === 0) {
        toast.success(`${ok} evento${ok !== 1 ? 's' : ''} aprobado${ok !== 1 ? 's' : ''}`)
      } else {
        toast.warning(`${ok} aprobado${ok !== 1 ? 's' : ''}, ${fail} fallido${fail !== 1 ? 's' : ''}`)
      }
      queryClient.invalidateQueries({ queryKey: ['events'] })
    },
  })

  const bulkRejectMutation = useMutation({
    mutationFn: (items: BulkRejectItem[]) => bulkReject(items),
    onError: (err: unknown) => {
      const message = bulkActionErrorMessage(err, 'rechazar')
      if (message) toast.error(message)
    },
    onSuccess: (result) => {
      const ok = result.succeeded.length
      const fail = result.failed.length
      if (fail === 0) {
        toast.success(`${ok} evento${ok !== 1 ? 's' : ''} rechazado${ok !== 1 ? 's' : ''}`)
      } else {
        toast.warning(`${ok} rechazado${ok !== 1 ? 's' : ''}, ${fail} fallido${fail !== 1 ? 's' : ''}`)
      }
      queryClient.invalidateQueries({ queryKey: ['events'] })
    },
  })

  return {
    approveMutation,
    rejectMutation,
    bulkApproveMutation,
    bulkRejectMutation,
    needsAbsentConfirmation,
    clearAbsentConfirmation: () => setNeedsAbsentConfirmation(false),
  }
}
