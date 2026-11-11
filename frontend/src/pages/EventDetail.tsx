import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { useEvent } from '@/hooks/useEvent'
import { useEventActions } from '@/hooks/useEventActions'
import { useEventChain } from '@/hooks/useEventChain'
import { useEventId } from '@/hooks/useEventId'
import { Can } from '@/hooks/useCan'
import { readApiError } from '@/api/errors'
import { EventTimeline } from '@/components/ui/EventTimeline'
import { DiffViewer } from '@/components/ui/DiffViewer'
import { RejectModal } from '@/components/ui/RejectModal'
import { ReleaseQuarantineModal } from '@/components/ui/ReleaseQuarantineModal'
import { Button } from '@/components/ui/Button'
import { DataState } from '@/components/ui/DataState'
import { EventNotFound } from '@/components/ui/EventNotFound'
import { HashChip } from '@/components/ui/HashChip'
import { PathLabel } from '@/components/ui/PathLabel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import {
  ActionFailedBadge,
  AckStatusBadge,
  OfflineDetectionBadge,
  QuarantineStateBadge,
  SymlinkBadge,
} from '@/components/ui/EventIndicators'
import type { RejectAction, ReleaseMode } from '@/api/actions'
import type { EventDetail as EventDetailData } from '@/api/events'
import { getActionErrorMeta, getAckErrorReason } from '@/utils/actionError'
import { getEventTypeGapMeta } from '@/utils/eventType'
import { getSeverityMeta } from '@/utils/severity'
import { formatAbsolute } from '@/utils/timeDisplay'
import { formatExe, formatPid, formatUid } from '@/utils/process'

export function EventDetail() {
  const eventId = useEventId()
  const navigate = useNavigate()

  const { data: event, isLoading, error, refetch, pollingStopped, restartPolling } = useEvent(eventId)
  const {
    approveMutation,
    rejectMutation,
    releaseQuarantineMutation,
    needsAbsentConfirmation,
    clearAbsentConfirmation,
  } = useEventActions({ eventId: eventId ?? undefined })

  const [rejectModalOpen, setRejectModalOpen] = useState(false)
  const [releaseModalOpen, setReleaseModalOpen] = useState(false)

  // US-10: la cadena se indexa por path (RN-21/RN-23) — un evento sin path
  // (D51/RN-145) nunca participa del mecanismo, así que ni se consulta.
  const { data: chain } = useEventChain(event?.path != null ? eventId : null)
  const chainItems = chain?.items ?? []
  const chainPosition = eventId != null ? chainItems.findIndex((item) => item.id === eventId) : -1
  const belongsToChain = chainPosition >= 0 && chainItems.length > 1

  // D93/RN-187: `/events/abc` and a 404 are «not found»; nothing is requested for a bad id.
  if (eventId === null || (error != null && readApiError(error).status === 404)) {
    return <EventNotFound eventId={eventId} />
  }

  if (error != null || isLoading || !event) {
    return (
      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="el evento"
        loadingLabel="Cargando evento..."
      >
        {null}
      </DataState>
    )
  }

  const isPending = approveMutation.isPending || rejectMutation.isPending
  // B6: the backend only resolves `pending` events (alert_only is informational).
  const canApprove = event.status === 'pending'

  function handleApprove() {
    approveMutation.mutate({
      event_id: event!.id,
      version: event!.version,
      confirm_absent: needsAbsentConfirmation || undefined,
    })
  }

  function handleRejectConfirm(action: RejectAction) {
    rejectMutation.mutate(
      { event_id: event!.id, version: event!.version, action },
      { onSuccess: () => setRejectModalOpen(false) },
    )
  }

  // D83/RN-177: la cuarentena es independiente del status (un rechazo con
  // cuarentena sigue `rejected`), así que el control se condiciona a
  // quarantine_state y no a status. Se deshabilita mientras un comando está en vuelo.
  const canRelease = event.quarantine_state === 'quarantined'
  const releaseInFlight = event.ack_status === 'pending'

  function handleReleaseConfirm(mode: ReleaseMode, reason: string) {
    releaseQuarantineMutation.mutate(
      { event_id: event!.id, mode, reason },
      { onSuccess: () => setReleaseModalOpen(false) },
    )
  }

  const gapMeta = event.path === null ? getEventTypeGapMeta(event.event_type) : null

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Encabezado */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Link to="/events" className="text-text-muted hover:text-text">
            Eventos
          </Link>
          <span className="text-text-muted">/</span>
          <span className="text-text">#{event.id}</span>
        </div>
        {/* D51/RN-145: without a path the title is the event type and its cause. */}
        {gapMeta ? (
          <div>
            <h1 className="text-xl font-semibold text-warning-fg">{gapMeta.label}</h1>
            <p className="mt-1 text-text-muted">{gapMeta.cause}</p>
          </div>
        ) : (
          <h1 className="m-0">
            <PathLabel path={event.path} variant="title" />
          </h1>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={event.status} />
          <SymlinkBadge isSymlink={event.is_symlink} target={event.symlink_target} />
          <OfflineDetectionBadge detectedOffline={event.detected_offline} />
          <ActionFailedBadge actionFailed={event.action_failed} />
          <AckStatusBadge ackStatus={event.ack_status} />
          <QuarantineStateBadge state={event.quarantine_state} />
        </div>
      </div>

      {/* Metadato de symlink (D33/RN-127): solo se muestra cuando is_symlink es true */}
      {event.is_symlink && (
        <FieldCard label="Destino del symlink">
          <span className="font-mono text-xs [overflow-wrap:anywhere]">
            {event.symlink_target ?? '(desconocido)'}
          </span>
        </FieldCard>
      )}

      {/* Causa del fallo de remediación (D36/RN-130): distingue un problema de
          despliegue de un problema de datos. Segundo nivel: no va en la tabla. */}
      <ActionErrorNote cause={event.action_error} />

      <CommandExecution event={event} pollingStopped={pollingStopped} onRefresh={restartPolling} />

      {/* Acciones (solo pending y solo admin) */}
      {canApprove && (
        <Can>
          <div className="flex flex-wrap gap-2">
            {needsAbsentConfirmation ? (
              <div className="flex flex-wrap items-center gap-3 rounded-panel border border-warning-line bg-warning-bg p-3">
                <span className="text-warning-fg">
                  El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del
                  baseline.
                </span>
                <Button variant="primary" size="sm" onClick={handleApprove} disabled={isPending}>
                  Confirmar
                </Button>
                <Button size="sm" onClick={clearAbsentConfirmation}>
                  Cancelar
                </Button>
              </div>
            ) : (
              <>
                <Button variant="primary" onClick={handleApprove} loading={approveMutation.isPending} disabled={isPending}>
                  {approveMutation.isPending ? 'Aprobando...' : 'Aprobar'}
                </Button>
                <Button variant="danger" onClick={() => setRejectModalOpen(true)} disabled={isPending}>
                  Rechazar
                </Button>
              </>
            )}
          </div>
        </Can>
      )}

      {/* Liberación de cuarentena (D83/RN-177): sólo con quarantine_state
          quarantined y sólo admin; deshabilitada con un comando pendiente. */}
      {canRelease && (
        <Can>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => setReleaseModalOpen(true)}
              disabled={releaseInFlight || releaseQuarantineMutation.isPending}
              title={releaseInFlight ? 'Hay un comando en curso para este evento' : undefined}
            >
              Liberar cuarentena
            </Button>
          </div>
        </Can>
      )}

      {/* US-10: posición en la cadena + acceso a la vista completa. Solo cuando
          el evento comparte path con al menos otro: una cadena de uno no es cadena. */}
      {belongsToChain && (
        <div className="flex flex-wrap items-center gap-3 rounded-panel border border-line bg-surface-raised p-3">
          <span className="text-text">
            Posición {chainPosition + 1} de {chainItems.length} en la cadena
          </span>
          <Link to={`/events/${eventId}/chain`} className="text-xs font-semibold text-accent underline">
            Ver cadena completa
          </Link>
        </div>
      )}

      {/* Detalles del evento */}
      <dl className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FieldCard label="Hash detectado">
          {event.hash_detected ? (
            <div className="space-y-1">
              <HashChip hash={event.hash_detected} />
              <p className="font-mono text-xs text-text-muted [overflow-wrap:anywhere]">{event.hash_detected}</p>
            </div>
          ) : (
            <span className="text-xs italic text-text-muted">Archivo ausente (no en baseline)</span>
          )}
        </FieldCard>

        {/* US-08 criterio 2: "tipo de acción" — derivado por el backend 1:1 desde status. */}
        <FieldCard label="Tipo de acción">
          <span className="font-mono text-xs">{event.action_type}</span>
        </FieldCard>

        <FieldCard label="Severidad">
          <span className={`font-mono text-xs font-semibold ${getSeverityMeta(event.severity).textClass}`}>
            {event.severity}
          </span>
        </FieldCard>

        <FieldCard label="Versión de optimistic lock">
          <span className="font-mono">{event.version}</span>
        </FieldCard>

        <FieldCard label="Fecha de creación">{formatAbsolute(event.created_at)}</FieldCard>
        <FieldCard label="Detectado">{formatAbsolute(event.detected_at)}</FieldCard>
        <FieldCard label="Recibido por backend">{formatAbsolute(event.received_at)}</FieldCard>

        {event.resolved_at && <FieldCard label="Resuelto">{formatAbsolute(event.resolved_at)}</FieldCard>}

        {event.resolved_by != null && (
          <FieldCard label="Resuelto por (user ID)">{event.resolved_by}</FieldCard>
        )}
      </dl>

      {/* Contexto de proceso */}
      {(event.process_pid != null || event.process_uid != null || event.process_exe != null) && (
        <section className="space-y-2 rounded-panel border border-line bg-surface-raised p-4">
          <h2 className="font-semibold text-text">Proceso que generó el evento</h2>
          <dl className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <dt className="text-xs text-text-muted">PID</dt>
              <dd className="font-mono">{formatPid(event.process_pid)}</dd>
            </div>
            {formatUid(event.process_uid) != null && (
              <div>
                <dt className="text-xs text-text-muted">UID</dt>
                <dd className="font-mono">{formatUid(event.process_uid)}</dd>
              </div>
            )}
            <div>
              <dt className="text-xs text-text-muted">Ejecutable</dt>
              <dd className="font-mono text-xs [overflow-wrap:anywhere]">{formatExe(event.process_exe)}</dd>
            </div>
          </dl>
        </section>
      )}

      <section className="space-y-3 rounded-panel border border-line bg-surface-raised p-4">
        <h2 className="font-semibold text-text">Diff de contenido</h2>
        {/* US-09: DiffViewer detecta el modo (texto/binario/no disponible) a partir de estas props. */}
        <DiffViewer
          diffText={event.diff_text}
          isBinary={event.is_binary}
          hashBefore={event.hash_expected}
          hashAfter={event.hash_detected}
          hexDumpBefore={event.hex_dump_before}
          hexDumpAfter={event.hex_dump_after}
        />
      </section>

      <section className="rounded-panel border border-line bg-surface-raised p-4">
        <EventTimeline event={event} />
      </section>

      <div>
        <Button variant="ghost" onClick={() => navigate(-1)}>
          Volver
        </Button>
      </div>

      <RejectModal
        event={event}
        open={rejectModalOpen}
        onClose={() => setRejectModalOpen(false)}
        onConfirm={handleRejectConfirm}
        isPending={rejectMutation.isPending}
      />

      <ReleaseQuarantineModal
        path={event.path}
        open={releaseModalOpen}
        onClose={() => setReleaseModalOpen(false)}
        onConfirm={handleReleaseConfirm}
        isPending={releaseQuarantineMutation.isPending}
      />
    </div>
  )
}

// Outcome of the last command (D30/RN-124, D93/RN-187). Shown only when there is one.
function CommandExecution({
  event,
  pollingStopped,
  onRefresh,
}: {
  event: EventDetailData
  pollingStopped: boolean
  onRefresh: () => void
}) {
  if (!event.ack_status) return null
  const reason = event.ack_status === 'failed' ? getAckErrorReason(event.ack_error) : null

  return (
    <section aria-label="Ejecución del comando" className="space-y-2 rounded-panel border border-line bg-surface-raised p-3">
      {event.ack_status === 'pending' && !pollingStopped && (
        <p className="text-text-muted" role="status">
          Esperando la confirmación del agente...
        </p>
      )}
      {event.ack_status === 'pending' && pollingStopped && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-text-muted">
            El comando sigue pendiente. El backend lo marca como vencido a los 5 minutos.
          </p>
          <Button size="sm" onClick={onRefresh}>
            <RefreshCw aria-hidden="true" size={14} />
            Actualizar
          </Button>
        </div>
      )}
      {event.ack_status === 'acked' && <p className="text-success-fg">El agente confirmó la ejecución.</p>}
      {event.ack_status === 'timeout' && (
        <p className="text-text-muted">El agente no confirmó a tiempo: el comando venció.</p>
      )}
      {reason && (
        <p className="text-danger-fg">{reason.startsWith('Motivo:') ? reason : `Motivo: ${reason}`}</p>
      )}
    </section>
  )
}

// Causa del fallo de remediación (D36/RN-130). Prosa, no el literal crudo salvo
// que el valor sea desconocido (getActionErrorMeta hace el fallback).
function ActionErrorNote({ cause }: { cause?: string | null }) {
  const meta = getActionErrorMeta(cause)
  if (!meta) return null
  return <div className={`rounded-control px-3 py-2 ${meta.className}`}>{meta.label}</div>
}

function FieldCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-panel border border-line bg-surface-raised p-3">
      <dt className="mb-1 text-xs text-text-muted">{label}</dt>
      <dd className="text-text">{children}</dd>
    </div>
  )
}
