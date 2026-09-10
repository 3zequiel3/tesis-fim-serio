interface DiffViewerProps {
  diffText: string
}

const DIFF_TRUNCATION_MARKER = '... [diff truncated by backend]'

/**
 * Render seguro y fiel del patch unificado. Mantener el patch intacto evita
 * concatenar hunks distantes o inventar continuidad y numeracion de lineas.
 */
export function DiffViewer({ diffText }: DiffViewerProps) {
  const wasTruncated = diffText.includes(DIFF_TRUNCATION_MARKER)

  return (
    <div className="text-sm" data-testid="content-diff">
      {wasTruncated && (
        <p className="mb-2 text-xs text-amber-300" role="status">
          Diff truncado por el límite de seguridad del backend.
        </p>
      )}
      <pre
        aria-label="Patch unificado"
        className="font-mono text-xs whitespace-pre-wrap break-all text-gray-200 overflow-x-auto"
      >
        {diffText}
      </pre>
    </div>
  )
}
