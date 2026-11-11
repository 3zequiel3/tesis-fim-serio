import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiErrorMessage, readApiError } from '@/api/errors'
import {
  approve,
  reject,
  bulkApprove,
  bulkReject,
  releaseQuarantine,
  type ReleaseQuarantineParams,
  type ApproveParams,
  type RejectParams,
  type RejectAction,
} from '@/api/actions'

/**
 * Un 422 en una acción bulk es una violación de contrato — el cuerpo que el
 * cliente emitió no fue el que el backend acepta —, no una falla operativa
 * como un timeout o un 5xx. Presentarlos con el mismo texto genérico es lo
 * que mantuvo el bulk-reject roto en silencio toda la vida del proyecto
 * (D-5 del design de frontend-severity-triage).
 */
function bulkActionErrorMessage(err: unknown, verb: string): string {
  if (readApiError(err).status === 422) {
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
      void queryClient.invalidateQueries({ queryKey: ['event', eventId] })
    }
    void queryClient.invalidateQueries({ queryKey: ['events'] })
  }

  function handleActionError(err: unknown) {
    // D90/RN-184: the code lives in `detail.code`; readApiError is the only reader.
    const { status, code } = readApiError(err)
    if (status === 409) {
      toast.error('Este evento ya fue resuelto o reemplazado. Refrescando lista...')
      invalidateEvent()
      return
    }
    if (status === 422 && code === 'absent_confirmation_required') {
      setNeedsAbsentConfirmation(true)
      return
    }
    // D90/RN-184: the backend message when there is one, never `[object Object]`.
    toast.error(apiErrorMessage(err, 'Error al procesar la acción'))
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
    onSuccess: (result, variables) => {
      invalidateEvent()
      // US-12 (D-8): condición de carrera entre el baseline_status leído al
      // abrir el modal y el estado real al confirmar — el backend responde
      // baseline_absent:true cuando el modal mostró las opciones correctivas
      // pero el baseline ya no tenía archivo.
      if (result.baseline_absent) {
        toast.info('El baseline ya no tiene archivo: el rechazo no ejecutó ninguna acción.')
      } else {
        // D93/RN-187: the 200 only means the command was queued; the agent's
        // outcome arrives later as the execution indicator (ack_status).
        toast.success(
          variables.action === 'quarantine'
            ? 'Rechazo registrado; cuarentena solicitada'
            : 'Rechazo registrado; restauración solicitada',
        )
      }
    },
  })

  // D83/RN-177: liberar una cuarentena. 202 = encolado; el resultado llega por
  // command_ack, así que el toast habla de "solicitada", no de "liberada".
  const releaseQuarantineMutation = useMutation({
    mutationFn: ({ event_id, mode, reason }: ReleaseQuarantineParams) =>
      releaseQuarantine(event_id, { mode, reason }),
    onError: (err: unknown) => {
      const { status, code } = readApiError(err)
      if (status === 409) {
        if (code === 'release_in_progress') {
          toast.error('Ya hay una liberación de cuarentena en curso para este evento.')
        } else if (code === 'quarantine_not_releasable') {
          toast.error('La cuarentena de este evento ya no se puede liberar.')
        } else {
          toast.error('No se pudo liberar la cuarentena: el evento cambió.')
        }
        invalidateEvent()
        return
      }
      toast.error('Error al solicitar la liberación de la cuarentena')
    },
    onSuccess: () => {
      invalidateEvent()
      toast.success('Liberación de cuarentena solicitada')
    },
  })

  const bulkApproveMutation = useMutation({
    mutationFn: (eventIds: number[]) => bulkApprove(eventIds),
    onError: (err: unknown) => {
      toast.error(bulkActionErrorMessage(err, 'aprobar'))
    },
    onSuccess: (result) => {
      const ok = result.succeeded.length
      const fail = result.failed.length
      if (fail === 0) {
        toast.success(`${ok} evento${ok !== 1 ? 's' : ''} aprobado${ok !== 1 ? 's' : ''}`)
      } else {
        toast.warning(`${ok} aprobado${ok !== 1 ? 's' : ''}, ${fail} fallido${fail !== 1 ? 's' : ''}`)
      }
      void queryClient.invalidateQueries({ queryKey: ['events'] })
    },
  })

  const bulkRejectMutation = useMutation({
    mutationFn: ({ eventIds, action }: { eventIds: number[]; action: RejectAction }) => bulkReject(eventIds, action),
    onError: (err: unknown) => {
      toast.error(bulkActionErrorMessage(err, 'rechazar'))
    },
    onSuccess: (result) => {
      const ok = result.succeeded.length
      const fail = result.failed.length
      if (fail === 0) {
        toast.success(`${ok} evento${ok !== 1 ? 's' : ''} rechazado${ok !== 1 ? 's' : ''}`)
      } else {
        toast.warning(`${ok} rechazado${ok !== 1 ? 's' : ''}, ${fail} fallido${fail !== 1 ? 's' : ''}`)
      }
      void queryClient.invalidateQueries({ queryKey: ['events'] })
    },
  })

  return {
    approveMutation,
    rejectMutation,
    releaseQuarantineMutation,
    bulkApproveMutation,
    bulkRejectMutation,
    needsAbsentConfirmation,
    clearAbsentConfirmation: () => setNeedsAbsentConfirmation(false),
  }
}
