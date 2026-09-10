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
})
