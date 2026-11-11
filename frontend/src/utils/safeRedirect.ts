// Where to send the user after login (frontend-auth spec): the route they were
// sent away from, but only if it is an internal path of the console.

interface FromLike {
  pathname?: unknown
  search?: unknown
  hash?: unknown
}

function isInternalPath(path: string): boolean {
  // `//host` and `/\host` are protocol-relative URLs that browsers treat as external.
  return /^\/(?![/\\])/.test(path) && !/[\u0000-\u001f]/.test(path)
}

export function postLoginTarget(from: unknown): string {
  let path: string | null = null
  if (typeof from === 'string') {
    path = from
  } else if (from && typeof from === 'object' && typeof (from as FromLike).pathname === 'string') {
    const f = from as { pathname: string; search?: unknown; hash?: unknown }
    path =
      f.pathname +
      (typeof f.search === 'string' ? f.search : '') +
      (typeof f.hash === 'string' ? f.hash : '')
  }
  if (!path || !isInternalPath(path)) return '/'
  if (path === '/login' || path.startsWith('/login?') || path.startsWith('/change-password')) return '/'
  return path
}
