// Splits a path into its directory (with trailing slash) and its file name.

export function splitPath(path: string): { dir: string; name: string } {
  const i = path.lastIndexOf('/')
  if (i === -1) return { dir: '', name: path }
  // A trailing slash (a directory) keeps the whole thing as the name.
  if (i === path.length - 1) {
    const trimmed = path.slice(0, -1)
    const j = trimmed.lastIndexOf('/')
    return { dir: trimmed.slice(0, j + 1), name: trimmed.slice(j + 1) + '/' }
  }
  return { dir: path.slice(0, i + 1), name: path.slice(i + 1) }
}
