import { useAuthStore } from '@/stores/auth.store'

/**
 * Whether the authenticated user may mutate (D93/RN-187, design D-6). Only
 * `admin` can; any other role gets the read-only console. Defensive: today
 * only `admin` exists (RN-29, RN-44).
 */
export function useCan(): boolean {
  return useAuthStore((s) => s.user?.role === 'admin')
}
