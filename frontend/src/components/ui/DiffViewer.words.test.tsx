import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DiffViewer } from './DiffViewer'

// D93/RN-187: changes inside a line are highlighted by WORD, not by character.
function spanTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('span')).map((s) => s.textContent ?? '')
}

describe('DiffViewer — comparación por palabras', () => {
  it('marca `no` y `yes` como palabras completas', () => {
    const { container } = render(
      <DiffViewer diffText={'@@ -1 +1 @@\n-PermitRootLogin no\n+PermitRootLogin yes\n'} />,
    )
    const texts = spanTexts(container)
    expect(texts).toContain('no')
    expect(texts).toContain('yes')
  })

  it('no fragmenta un número que comparte dígitos en letras sueltas', () => {
    const { container } = render(<DiffViewer diffText={'@@ -1 +1 @@\n-Port 2222\n+Port 2022\n'} />)
    const texts = spanTexts(container)
    // Character mode would highlight '22' / '0' / '2' separately and never '2222' as a unit.
    expect(texts).toContain('2222')
    expect(texts).toContain('2022')
  })
})
