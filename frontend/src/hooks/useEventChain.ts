import { useQuery } from '@tanstack/react-query'
import { getEventChain, type EventChainResponse } from '@/api/events'

// US-10: cadena de eventos del mismo path. `id` puede ser cualquier evento
// de la cadena (el backend resuelve el path desde ese evento y devuelve
// todos los que lo comparten). Deshabilitado para un evento sin path
// (D51/RN-145) — un pathless nunca participa del mecanismo de cadena, así
// que EventDetail.tsx pasa `null` en ese caso.
export function useEventChain(id: number | null | undefined) {
  return useQuery<EventChainResponse>({
    queryKey: ['event-chain', id],
    queryFn: () => getEventChain(id as number),
    enabled: id != null,
  })
}
