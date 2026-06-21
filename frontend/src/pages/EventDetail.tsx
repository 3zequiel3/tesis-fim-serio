import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useEvent } from '@/hooks/useEvent'
import { useEventActions } from '@/hooks/useEventActions'
import { DiffViewer } from '@/components/ui/DiffViewer'
import { EventTimeline } from '@/components/ui/EventTimeline'
import { RejectModal } from '@/components/ui/RejectModal'
import type { RejectAction } from '@/api/actions'

export function EventDetail() {
  const { id } = useParams<{ id: string }>()
  const eventId = id ? Number(id) : null
  const navigate = useNavigate()

  const { data: event, isLoading, error } = useEvent(eventId)
  const {
    approveMutation,
    rejectMutation,
    needsAbsentConfirmation,
    clearAbsentConfirmation,
  } = useEventActions({ eventId: eventId ?? undefined })

  const [rejectModalOpen, setRejectModalOpen] = useState(false)

  // Manejo de 404
  const is404 =
    error != null &&
    (error as { response?: { status?: number } })?.response?.status === 404

  if (is404) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-2xl font-semibold text-gray-400">Evento no encontrado</p>
        <p className="text-sm text-gray-500 mt-2">
          El evento #{eventId} no existe o fue eliminado.
        </p>
        <Link to="/events" className="mt-4 inline-block text-blue-400 hover:text-blue-300 text-sm">
          Volver a eventos
        </Link>
      </div>
    )
  }

  if (isLoading || !event) {
    return (
      <div className="py-16 text-center text-gray-500">
        Cargando evento...
      </div>
    )
  }

  const isPending = approveMutation.isPending || rejectMutation.isPending
  const canApprove = event.status === 'pending' || event.status === 'alert_only'

  function handleApprove() {
    if (!event) return
    approveMutation.mutate({
      event_id: event.id,
      version: event.version,
      confirm_absent: needsAbsentConfirmation || undefined,
    })
  }

  function handleRejectConfirm(action: RejectAction) {
    if (!event) return
    rejectMutation.mutate(
      { event_id: event.id, version: event.version, action },
      { onSuccess: () => setRejectModalOpen(false) }
    )
  }

  return (
    <div className="max-w-4xl mx-auto py-6 px-4 space-y-6">
      {/* Encabezado */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link to="/events" className="text-gray-500 hover:text-gray-300 text-sm">
              Eventos
            </Link>
            <span className="text-gray-600">/</span>
            <span className="text-gray-300 text-sm">#{event.id}</span>
          </div>
          <h1 className="text-lg font-semibold text-white break-all">
            {event.path}
          </h1>
        </div>
        <StatusBadge status={event.status} />
      </div>

      {/* Acciones (solo si está pendiente o alert_only) */}
      {canApprove && (
        <div className="flex gap-2">
          {needsAbsentConfirmation ? (
            <div className="flex items-center gap-3 p-3 bg-yellow-950 border border-yellow-800 rounded text-sm">
              <span className="text-yellow-300">
                El archivo no está en el baseline. ¿Confirmar aprobación de ausencia?
              </span>
              <button
                onClick={handleApprove}
                disabled={isPending}
                className="px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded text-xs font-medium disabled:opacity-50"
              >
                Confirmar
              </button>
              <button
                onClick={clearAbsentConfirmation}
                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
              >
                Cancelar
              </button>
            </div>
          ) : (
            <>
              <button
                onClick={handleApprove}
                disabled={isPending}
                className="px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded text-sm font-medium disabled:opacity-50"
              >
                {approveMutation.isPending ? 'Aprobando...' : 'Aprobar'}
              </button>
              <button
                onClick={() => setRejectModalOpen(true)}
                disabled={isPending}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded text-sm font-medium disabled:opacity-50"
              >
                Rechazar
              </button>
            </>
          )}
        </div>
      )}

      {/* Detalles del evento */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FieldCard label="Hash detectado">
          {event.hash_detected ? (
            <span className="font-mono text-xs break-all text-red-400">
              {event.hash_detected}
            </span>
          ) : (
            <span className="text-gray-500 text-xs italic">
              Archivo ausente (no en baseline)
            </span>
          )}
        </FieldCard>

        <FieldCard label="Versión de optimistic lock">
          <span className="font-mono">{event.version}</span>
        </FieldCard>

        <FieldCard label="Detectado">
          {new Date(event.detected_at).toLocaleString('es-AR')}
        </FieldCard>

        <FieldCard label="Recibido por backend">
          {new Date(event.received_at).toLocaleString('es-AR')}
        </FieldCard>

        {event.resolved_at && (
          <FieldCard label="Resuelto">
            {new Date(event.resolved_at).toLocaleString('es-AR')}
          </FieldCard>
        )}

        {event.resolved_by != null && (
          <FieldCard label="Resuelto por (user ID)">
            {event.resolved_by}
          </FieldCard>
        )}
      </div>

      {/* Contexto de proceso */}
      {(event.process_pid != null || event.process_uid != null || event.process_exe) && (
        <section className="bg-gray-800 border border-gray-700 rounded p-4 space-y-2">
          <h2 className="text-sm font-semibold text-gray-300">Proceso que generó el evento</h2>
          <dl className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm">
            {event.process_pid != null && (
              <div>
                <dt className="text-gray-500 text-xs">PID</dt>
                <dd className="font-mono text-gray-200">{event.process_pid}</dd>
              </div>
            )}
            {event.process_uid != null && (
              <div>
                <dt className="text-gray-500 text-xs">UID</dt>
                <dd className="font-mono text-gray-200">{event.process_uid}</dd>
              </div>
            )}
            {event.process_exe && (
              <div>
                <dt className="text-gray-500 text-xs">Ejecutable</dt>
                <dd className="font-mono text-xs text-gray-200 break-all">{event.process_exe}</dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {/* DiffViewer */}
      <section className="bg-gray-800 border border-gray-700 rounded p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Diff de contenido</h2>
        {event.hash_detected ? (
          <div>
            <p className="text-xs text-gray-500 mb-3">
              El agente no envía contenido de archivo — solo el hash SHA-256. Para ver el diff real,
              accedé al archivo directamente en el host monitoreado.
            </p>
            <DiffViewer
              oldValue="(contenido baseline no disponible)"
              newValue="(contenido detectado no disponible)"
              newHash={event.hash_detected}
            />
          </div>
        ) : (
          <p className="text-xs text-gray-500">
            Archivo ausente — no hay contenido que comparar.
          </p>
        )}
      </section>

      {/* Timeline */}
      <section className="bg-gray-800 border border-gray-700 rounded p-4">
        <EventTimeline event={event} />
      </section>

      {/* Botón volver */}
      <div>
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          Volver
        </button>
      </div>

      {/* Modal de rechazo */}
      <RejectModal
        event={event}
        open={rejectModalOpen}
        onClose={() => setRejectModalOpen(false)}
        onConfirm={handleRejectConfirm}
        isPending={rejectMutation.isPending}
      />
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    pending: 'bg-yellow-900 text-yellow-300 border-yellow-800',
    approved: 'bg-green-900 text-green-300 border-green-800',
    rejected: 'bg-red-900 text-red-300 border-red-800',
    superseded: 'bg-gray-700 text-gray-400 border-gray-600',
    auto_restored: 'bg-blue-900 text-blue-300 border-blue-800',
    quarantined: 'bg-orange-900 text-orange-300 border-orange-800',
    alert_only: 'bg-purple-900 text-purple-300 border-purple-800',
  }
  const cls = classes[status] ?? 'bg-gray-700 text-gray-300 border-gray-600'
  return (
    <span className={`shrink-0 px-2.5 py-1 rounded border text-sm font-mono ${cls}`}>
      {status}
    </span>
  )
}

function FieldCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded p-3">
      <dt className="text-xs text-gray-500 mb-1">{label}</dt>
      <dd className="text-sm text-gray-200">{children}</dd>
    </div>
  )
}
