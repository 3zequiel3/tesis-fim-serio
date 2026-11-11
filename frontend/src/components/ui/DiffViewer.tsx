import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued'
import { useTheme } from '@/hooks/useTheme'

interface DiffViewerProps {
  diffText?: string | null
  // US-09: modo binario. isBinary distingue "sin diff porque el contenido es
  // binario" (hash + hex dump disponibles) de "sin diff por otra razón"
  // (p. ej. sin contenido previo utilizable) — el componente decide el modo
  // de render, no el caller (auto-detección exigida por el criterio).
  isBinary?: boolean
  hashBefore?: string | null
  hashAfter?: string | null
  hexDumpBefore?: string | null
  hexDumpAfter?: string | null
}

const DIFF_TRUNCATION_MARKER = '... [diff truncated by backend]'
const HUNK_HEADER = /^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*$/

interface Hunk {
  header: string
  oldValue: string
  newValue: string
}

/**
 * Reconstruye, por hunk, el texto "antes"/"después" de un patch unificado
 * acotado. react-diff-viewer-continued espera contenido completo de cada
 * lado (no un patch ya calculado), así que se reconstruye SOLO lo que el
 * patch ya trae — nunca se lee ni se pide más contenido del que el backend
 * ya entregó.
 *
 * Los hunks se renderizan por separado (nunca concatenados): dos hunks
 * distantes de un mismo patch no deben leerse como contenido contiguo — la
 * misma garantía que el render anterior en <pre> ya daba (ver
 * DiffViewer.test.ts, "preserva encabezados y offsets... sin crear
 * continuidad falsa"), ahora preservada en vez de perdida al adoptar la
 * librería mandada por W8.
 */
function parseUnifiedDiff(diffText: string): { fileHeaders: string[]; hunks: Hunk[] } {
  const fileHeaders: string[] = []
  const hunks: Hunk[] = []
  let current: Hunk | null = null

  for (const line of diffText.split('\n')) {
    if (HUNK_HEADER.test(line)) {
      if (current) hunks.push(current)
      current = { header: line, oldValue: '', newValue: '' }
      continue
    }
    if (current === null) {
      if (line.startsWith('--- ') || line.startsWith('+++ ')) {
        fileHeaders.push(line)
      }
      continue
    }
    if (line.startsWith('-')) {
      current.oldValue += line.slice(1) + '\n'
    } else if (line.startsWith('+')) {
      current.newValue += line.slice(1) + '\n'
    } else if (line.startsWith(' ')) {
      current.oldValue += line.slice(1) + '\n'
      current.newValue += line.slice(1) + '\n'
    }
    // Cualquier otra línea (p. ej. "\ No newline at end of file", o el
    // marcador de truncado del backend) no forma parte del hunk reconstruido.
  }
  if (current) hunks.push(current)
  return { fileHeaders, hunks }
}

// Reads a design token of the ACTIVE theme (globals.css). The library takes
// plain color strings, so the CSS variable is resolved here; the fallback only
// matters where there is no stylesheet (tests).
function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function diffStyles(isDark: boolean) {
  const palette = {
    diffViewerBackground: token('--color-surface-raised', isDark ? '#1b2532' : '#ffffff'),
    diffViewerColor: token('--color-text', isDark ? '#e4e9ef' : '#18222e'),
    addedBackground: token('--color-success-bg', isDark ? '#15352a' : '#d9f1e4'),
    addedColor: token('--color-text', isDark ? '#e4e9ef' : '#18222e'),
    removedBackground: token('--color-danger-bg', isDark ? '#3d1f1f' : '#fadada'),
    removedColor: token('--color-text', isDark ? '#e4e9ef' : '#18222e'),
    // Whole words, not letters: a stronger tint of the same line color.
    wordAddedBackground: token('--color-success-line', isDark ? '#25604a' : '#9fd2b8'),
    wordRemovedBackground: token('--color-danger-line', isDark ? '#6e3330' : '#e3aaa5'),
    addedGutterBackground: token('--color-success-bg', isDark ? '#15352a' : '#d9f1e4'),
    removedGutterBackground: token('--color-danger-bg', isDark ? '#3d1f1f' : '#fadada'),
    gutterBackground: token('--color-surface', isDark ? '#141c26' : '#f2f4f7'),
    gutterBackgroundDark: token('--color-surface', isDark ? '#141c26' : '#f2f4f7'),
    gutterColor: token('--color-text-muted', isDark ? '#93a1b1' : '#56636f'),
    codeFoldBackground: token('--color-surface', isDark ? '#141c26' : '#f2f4f7'),
    codeFoldGutterBackground: token('--color-surface', isDark ? '#141c26' : '#f2f4f7'),
    codeFoldContentColor: token('--color-text-muted', isDark ? '#93a1b1' : '#56636f'),
    emptyLineBackground: token('--color-surface', isDark ? '#141c26' : '#f2f4f7'),
  }
  return { variables: { dark: palette, light: palette } }
}

function TextDiff({ diffText }: { diffText: string }) {
  const { theme } = useTheme()
  const wasTruncated = diffText.includes(DIFF_TRUNCATION_MARKER)
  const { fileHeaders, hunks } = parseUnifiedDiff(diffText)

  return (
    <div className="text-sm" data-testid="content-diff">
      {wasTruncated && (
        <p className="mb-2 text-xs text-warning-fg" role="status">
          Diff truncado por el límite de seguridad del backend.
        </p>
      )}
      <div aria-label="Patch unificado" className="space-y-4">
        {fileHeaders.map((line) => (
          <p key={line} className="font-mono text-xs text-text-muted">
            {line}
          </p>
        ))}
        {hunks.length === 0 ? (
          <pre className="font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere] text-text overflow-x-auto">
            {diffText}
          </pre>
        ) : (
          hunks.map((hunk, i) => (
            <div key={i}>
              <p className="font-mono text-xs text-text-muted mb-1">{hunk.header}</p>
              <div className="overflow-x-auto">
                <ReactDiffViewer
                  oldValue={hunk.oldValue}
                  newValue={hunk.newValue}
                  splitView
                  useDarkTheme={theme === 'dark'}
                  // D93/RN-187: highlight whole words, not characters.
                  compareMethod={DiffMethod.WORDS_WITH_SPACE}
                  styles={diffStyles(theme === 'dark')}
                />
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function BinaryComparison({
  hashBefore,
  hashAfter,
  hexDumpBefore,
  hexDumpAfter,
}: {
  hashBefore: string | null
  hashAfter: string | null
  hexDumpBefore: string | null
  hexDumpAfter: string | null
}) {
  const hashesDiffer = hashBefore !== null && hashBefore !== hashAfter

  return (
    <div className="space-y-3 text-sm" data-testid="binary-diff">
      <div className="flex items-center gap-2">
        <span className={hashesDiffer ? 'text-danger-fg' : 'text-success-fg'} aria-hidden="true">
          {hashesDiffer ? '✗' : '✓'}
        </span>
        <span className="text-text">
          {hashesDiffer ? 'Los hashes difieren' : 'Los hashes coinciden'}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <p className="text-xs text-text-muted mb-1">Hash anterior</p>
          <p className="font-mono text-xs [overflow-wrap:anywhere] text-text">
            {hashBefore ?? 'sin baseline'}
          </p>
          <p className="text-xs text-text-muted mt-2 mb-1">Volcado hexadecimal (primeros bytes)</p>
          <pre className="font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere] text-text-muted bg-surface rounded-control p-2 overflow-x-auto">
            {hexDumpBefore ?? 'contenido anterior no disponible'}
          </pre>
        </div>
        <div>
          <p className="text-xs text-text-muted mb-1">Hash actual</p>
          <p className="font-mono text-xs [overflow-wrap:anywhere] text-danger-fg">{hashAfter ?? '—'}</p>
          <p className="text-xs text-text-muted mt-2 mb-1">Volcado hexadecimal (primeros bytes)</p>
          <pre className="font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere] text-text bg-surface rounded-control p-2 overflow-x-auto">
            {hexDumpAfter ?? 'no disponible'}
          </pre>
        </div>
      </div>
    </div>
  )
}

/**
 * Render seguro y fiel del diff de un evento. Detecta automáticamente el
 * modo (texto / binario / no disponible) a partir de las props que ya trae
 * el detalle del evento:
 * - diffText presente -> patch unificado, vía react-diff-viewer-continued
 *   con escapado activo (W8: PROHIBIDO dangerouslySetInnerHTML en todo el
 *   codebase — ni este componente ni la librería lo usan).
 * - diffText ausente + isBinary -> comparación de hashes + hex dump parcial
 *   lado a lado.
 * - ninguno de los dos -> mensaje de ausencia.
 */
export function DiffViewer({
  diffText = null,
  isBinary = false,
  hashBefore = null,
  hashAfter = null,
  hexDumpBefore = null,
  hexDumpAfter = null,
}: DiffViewerProps) {
  if (diffText) {
    return <TextDiff diffText={diffText} />
  }
  if (isBinary) {
    return (
      <BinaryComparison
        hashBefore={hashBefore}
        hashAfter={hashAfter}
        hexDumpBefore={hexDumpBefore}
        hexDumpAfter={hexDumpAfter}
      />
    )
  }
  return (
    <p className="text-sm text-text-muted italic">
      Diff textual no disponible para este evento.
    </p>
  )
}
