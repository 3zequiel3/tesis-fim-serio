import type { ReactNode } from 'react'
import { useCan } from '@/hooks/useCan'

/** Renders its children only for users who can mutate. */
export function Can({ children }: { children: ReactNode }) {
  return useCan() ? <>{children}</> : null
}
