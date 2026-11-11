// The path as typographic specimen (design D-1): dimmed directory, emphasized
// file name, monospace. Long paths break instead of widening the page.

import { splitPath } from '@/utils/pathSplit'

interface PathLabelProps {
  path: string | null | undefined
  /** `title` composes the path large (detail header). */
  variant?: 'inline' | 'title'
  className?: string
}

export function PathLabel({ path, variant = 'inline', className = '' }: PathLabelProps) {
  const size = variant === 'title' ? 'text-2xl' : 'text-sm'
  const nameWeight = variant === 'title' ? 'font-bold' : 'font-semibold'
  if (!path) {
    return <span className={`font-mono text-text-muted ${size} ${className}`}>—</span>
  }
  const { dir, name } = splitPath(path)
  // The full path is exposed once, as plain text, to assistive tech and to
  // text search; the split styling is decoration only.
  return (
    <span title={path} className={`font-mono [overflow-wrap:anywhere] ${size} ${className}`}>
      <span className="sr-only">{path}</span>
      <span aria-hidden="true">
        <span className="text-text-muted">{dir}</span>
        <span className={`${nameWeight} text-text`}>{name}</span>
      </span>
    </span>
  )
}
