import { QueryClient } from '@tanstack/react-query'

// Shared instance (design D-5): the auth store has to clear the cache on
// logout, expired session and password change, outside of React.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})
