// Process context of an event (D93/RN-187): a missing or placeholder value is
// shown as «desconocido» instead of `?`, `0` or nothing. A uid of 0 is root and
// stays a real value.

export const UNKNOWN_PROCESS = 'desconocido'

/** pid 0 and null both mean the agent could not attribute the change. */
export function formatPid(pid: number | null | undefined): string {
  return pid == null || pid === 0 ? UNKNOWN_PROCESS : String(pid)
}

export function formatUid(uid: number | null | undefined): string | null {
  return uid == null ? null : String(uid)
}

/** The agent writes `?` when /proc could not be read. */
export function formatExe(exe: string | null | undefined): string {
  return exe == null || exe === '' || exe === '?' ? UNKNOWN_PROCESS : exe
}

/**
 * One-line process label for the table, or null when there is nothing to say:
 * all three fields null is a normal event without process context (US-06).
 */
export function processContextLabel(item: {
  process_pid: number | null
  process_uid: number | null
  process_exe: string | null
}): string | null {
  if (item.process_pid == null && item.process_uid == null && item.process_exe == null) return null
  const parts: string[] = []
  if (item.process_pid != null) parts.push(`pid ${formatPid(item.process_pid)}`)
  const uid = formatUid(item.process_uid)
  if (uid != null) parts.push(`uid ${uid}`)
  const exe = formatExe(item.process_exe)
  return parts.length > 0 ? `${exe} (${parts.join(', ')})` : exe
}
