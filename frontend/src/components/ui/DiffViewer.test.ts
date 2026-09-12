import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createElement } from 'react'
import { DiffViewer } from './DiffViewer'

describe('DiffViewer', () => {
  it('preserva encabezados y offsets de múltiples hunks sin crear continuidad falsa', () => {
    const diff = [
      '--- a/etc/hosts',
      '+++ b/etc/hosts',
      '@@ -1 +1 @@',
      '-old first',
      '+new first',
      '@@ -100 +100 @@',
      '-old distant',
      '+new distant',
    ].join('\n')

    render(createElement(DiffViewer, { diffText: diff }))

    expect(screen.getByLabelText('Patch unificado')).toHaveTextContent('--- a/etc/hosts')
    expect(screen.getByLabelText('Patch unificado')).toHaveTextContent('@@ -1 +1 @@')
    expect(screen.getByLabelText('Patch unificado')).toHaveTextContent('@@ -100 +100 @@')
  })

  it('hace visible que el backend truncó el patch', () => {
    render(createElement(DiffViewer, {
      diffText: '@@ -1 +1 @@\n-old\n+new\n... [diff truncated by backend]\n',
    }))

    expect(screen.getByRole('status')).toHaveTextContent('Diff truncado')
  })

  it('detecta modo binario automáticamente y muestra hash + hex dump lado a lado', () => {
    render(createElement(DiffViewer, {
      diffText: null,
      isBinary: true,
      hashBefore: 'aaaa',
      hashAfter: 'bbbb',
      hexDumpBefore: '00000000  89 50 4e 47',
      hexDumpAfter: '00000000  ff ee dd cc',
    }))

    const view = screen.getByTestId('binary-diff')
    expect(view).toHaveTextContent('aaaa')
    expect(view).toHaveTextContent('bbbb')
    expect(view).toHaveTextContent('89 50 4e 47')
    expect(view).toHaveTextContent('ff ee dd cc')
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })

  it('indica visualmente que los hashes difieren en modo binario', () => {
    render(createElement(DiffViewer, {
      diffText: null,
      isBinary: true,
      hashBefore: 'aaaa',
      hashAfter: 'bbbb',
      hexDumpBefore: null,
      hexDumpAfter: '00000000  ff ee dd cc',
    }))

    expect(screen.getByText(/difieren/i)).toBeInTheDocument()
  })

  it('declara ausencia de diff cuando no hay patch textual ni contenido binario', () => {
    render(createElement(DiffViewer, { diffText: null, isBinary: false }))

    expect(screen.getByText('Diff textual no disponible para este evento.')).toBeInTheDocument()
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
    expect(screen.queryByTestId('binary-diff')).not.toBeInTheDocument()
  })

  it('nunca usa dangerouslySetInnerHTML (W8): el patch se ve como texto escapado', () => {
    const diff = [
      '--- a/etc/hosts',
      '+++ b/etc/hosts',
      '@@ -1 +1 @@',
      '-<script>alert(1)</script>',
      '+safe',
    ].join('\n')

    const { container } = render(createElement(DiffViewer, { diffText: diff }))

    // Si el contenido se hubiera inyectado como HTML crudo, el navegador
    // parsearía un <script> real dentro del árbol renderizado.
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByLabelText('Patch unificado')).toHaveTextContent('<script>alert(1)</script>')
  })
})
