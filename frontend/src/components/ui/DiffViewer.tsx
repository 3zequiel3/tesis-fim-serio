import ReactDiffViewer from 'react-diff-viewer-continued'

interface DiffViewerProps {
  oldValue: string
  newValue: string
  /** Hash del baseline (para mostrar en caso binario) */
  oldHash?: string | null
  /** Hash detectado (para mostrar en caso binario) */
  newHash?: string | null
}

/**
 * Detecta si un string contiene contenido binario (byte nulo).
 * Exportada para tests unitarios.
 */
export function isBinaryContent(s: string): boolean {
  return s.includes('\0')
}

/**
 * Genera un hex dump de los primeros maxBytes bytes del string.
 * Exportada para tests unitarios.
 */
export function toHexDump(s: string, maxBytes = 256): string {
  const bytes = s.slice(0, maxBytes)
  return Array.from(bytes)
    .map((c) => c.charCodeAt(0).toString(16).padStart(2, '0'))
    .join(' ')
}

/**
 * Componente de diff seguro.
 * - NUNCA usa innerHTML peligroso ni renderizado inseguro (RN-96 / W8).
 * - Detecta binario por byte nulo y muestra hash + hex dump en su lugar.
 * - Para texto usa react-diff-viewer-continued en vista split.
 */
export function DiffViewer({ oldValue, newValue, oldHash, newHash }: DiffViewerProps) {
  const isBinary = isBinaryContent(oldValue) || isBinaryContent(newValue)

  if (isBinary) {
    return (
      <div className="font-mono text-sm p-4 bg-gray-900 text-gray-100 rounded">
        <p className="mb-2 font-semibold text-yellow-400">
          Archivo binario — diff de texto no disponible
        </p>
        {(oldHash || newHash) && (
          <div className="mb-3 text-xs space-y-1">
            {oldHash && (
              <p>
                <span className="text-gray-400">Hash baseline:</span>{' '}
                <span className="text-green-400">{oldHash}</span>
              </p>
            )}
            {newHash && (
              <p>
                <span className="text-gray-400">Hash detectado:</span>{' '}
                <span className="text-red-400">{newHash}</span>
              </p>
            )}
          </div>
        )}
        <p className="mb-1 text-gray-400 text-xs">Hex dump (primeros 256 bytes del contenido detectado):</p>
        <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">
          {toHexDump(newValue || oldValue)}
        </pre>
      </div>
    )
  }

  return (
    <div className="text-sm">
      <ReactDiffViewer
        oldValue={oldValue}
        newValue={newValue}
        splitView={true}
      />
    </div>
  )
}
