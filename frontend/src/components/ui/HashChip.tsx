import { Check, Copy } from 'lucide-react'
import { useState } from 'react'

// First 8 hex in two groups of 4 (`a3f9 1c02`); the full hash is in `title`
// and copied to the clipboard on click (design D-1).

export function formatHash(hash: string): string {
  const hex = hash.replace(/^[a-z0-9]+:/i, '')
  const head = hex.slice(0, 8)
  return head.length > 4 ? `${head.slice(0, 4)} ${head.slice(4)}` : head
}

export function HashChip({ hash, className = '' }: { hash: string | null | undefined; className?: string }) {
  const [copied, setCopied] = useState(false)
  if (!hash) return <span className={`font-mono text-text-muted ${className}`}>—</span>

  async function copy() {
    try {
      await navigator.clipboard.writeText(hash as string)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard may be unavailable (insecure context): the full hash stays in the title.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      title={hash}
      aria-label={copied ? 'Hash copiado' : `Copiar hash ${hash}`}
      className={`inline-flex items-center gap-1.5 rounded-control border border-line bg-surface px-2 py-0.5 font-mono text-xs text-text hover:bg-surface-hover ${className}`}
    >
      {formatHash(hash)}
      {copied ? <Check aria-hidden="true" size={12} /> : <Copy aria-hidden="true" size={12} />}
    </button>
  )
}
