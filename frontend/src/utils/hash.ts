// Short display form of a hash (design D-1).

export function formatHash(hash: string): string {
  const hex = hash.replace(/^[a-z0-9]+:/i, '')
  const head = hex.slice(0, 8)
  return head.length > 4 ? `${head.slice(0, 4)} ${head.slice(4)}` : head
}
