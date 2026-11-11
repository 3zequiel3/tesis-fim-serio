import { Link } from 'react-router-dom'

/** Shared «not found» state of the detail and chain pages (D93/RN-187). */
export function EventNotFound({ eventId }: { eventId?: number | null }) {
  return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <p className="text-2xl font-semibold text-text">Evento no encontrado</p>
      <p className="mt-2 text-text-muted">
        {eventId != null ? `El evento #${eventId} no existe o fue eliminado.` : 'El identificador del evento no es válido.'}
      </p>
      <Link to="/events" className="mt-4 inline-block font-semibold text-accent underline">
        Volver a eventos
      </Link>
    </div>
  )
}
