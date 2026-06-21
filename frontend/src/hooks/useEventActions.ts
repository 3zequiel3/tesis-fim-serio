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
  type RejectAction,
} from '@/api/actions'

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
      if (axios.isAxiosError(err)) {
        toast.error('Error al aprobar en lote')
      }
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
    mutationFn: ({ items, action }: { items: BulkRejectItem[]; action: RejectAction }) =>
      bulkReject(items, action),
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        toast.error('Error al rechazar en lote')
      }
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
