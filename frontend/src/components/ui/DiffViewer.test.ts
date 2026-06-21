import { describe, it, expect } from 'vitest'
import { isBinaryContent, toHexDump } from './DiffViewer'

describe('isBinaryContent', () => {
  it('retorna false para texto normal', () => {
    expect(isBinaryContent('hello world')).toBe(false)
    expect(isBinaryContent('')).toBe(false)
    expect(isBinaryContent('/etc/passwd contenido\nroot:x:0:0')).toBe(false)
  })

  it('retorna true para strings con byte nulo', () => {
    expect(isBinaryContent('data\0binary')).toBe(true)
    expect(isBinaryContent('\0')).toBe(true)
    expect(isBinaryContent('prefix\0suffix')).toBe(true)
  })

  it('retorna true para ELF header (binario real)', () => {
    // Simula un ELF header: 0x7f + "ELF" + null bytes
    const elfLike = '\x7fELF\0\0\0\0'
    expect(isBinaryContent(elfLike)).toBe(true)
  })
})

describe('toHexDump', () => {
  it('convierte texto ASCII a hex', () => {
    const result = toHexDump('AB')
    expect(result).toBe('41 42')
  })

  it('trunca a maxBytes', () => {
    const long = 'a'.repeat(300)
    const result = toHexDump(long, 4)
    // 4 bytes = "61 61 61 61"
    expect(result).toBe('61 61 61 61')
  })

  it('trunca al default de 256 bytes', () => {
    const long = 'x'.repeat(300)
    const result = toHexDump(long)
    const parts = result.split(' ')
    expect(parts).toHaveLength(256)
  })

  it('maneja string vacío', () => {
    expect(toHexDump('')).toBe('')
  })
})
