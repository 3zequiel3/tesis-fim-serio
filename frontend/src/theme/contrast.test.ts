import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { contrastRatio } from './contrast'

// Single source of truth: the tokens are read from globals.css itself, so a
// retouched hex that breaks AA fails here (D93/RN-187, task 2.2).
const css = readFileSync(resolve(__dirname, '../globals.css'), 'utf8')

function block(opening: RegExp): string {
  const match = opening.exec(css)
  if (!match) throw new Error(`Block not found: ${String(opening)}`)
  let depth = 1
  let i = match.index + match[0].length
  const start = i
  while (depth > 0 && i < css.length) {
    if (css[i] === '{') depth++
    if (css[i] === '}') depth--
    i++
  }
  return css.slice(start, i - 1)
}

function vars(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/--color-([a-z_-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2]
  return out
}

const dark = vars(block(/@theme static\s*\{/))
const light = { ...dark, ...vars(block(/\[data-theme="light"\]\s*\{/)) }

const STATUSES = [
  'pending',
  'approved',
  'rejected',
  'superseded',
  'auto_restored',
  'quarantined',
  'alert_only',
]
const TONES = ['danger', 'warning', 'success', 'info', 'neutral']
const SEVERITIES = ['critical', 'high', 'medium', 'low']

function pairs(t: Record<string, string>): Array<[string, string, string]> {
  const out: Array<[string, string, string]> = []
  for (const bg of ['surface', 'surface-raised', 'surface-hover']) {
    out.push(['text', 'text', bg], ['text-muted', 'text-muted', bg])
  }
  for (const bg of ['surface', 'surface-raised']) out.push(['accent link', 'accent', bg])
  out.push(['on-accent', 'on-accent', 'accent'])
  out.push(['on-accent hover', 'on-accent', 'accent-hover'])
  out.push(['accent-soft', 'accent-soft-text', 'accent-soft'])
  out.push(['on-danger', 'on-danger', 'danger-solid'])
  out.push(['on-danger hover', 'on-danger', 'danger-solid-hover'])
  for (const s of STATUSES) out.push([`status ${s}`, `status-${s}-fg`, `status-${s}-bg`])
  for (const s of TONES) {
    out.push([`tone ${s}`, `${s}-fg`, `${s}-bg`])
    out.push([`tone ${s} on raised`, `${s}-fg`, 'surface-raised'])
  }
  for (const s of SEVERITIES) {
    for (const bg of ['surface', 'surface-raised']) out.push([`severity ${s}`, `sev-${s}-fg`, bg])
  }
  for (const [, fg, bg] of out) {
    if (!t[fg] || !t[bg]) throw new Error(`Missing token in pair ${fg} / ${bg}`)
  }
  return out
}

describe.each([
  ['dark', dark],
  ['light', light],
])('contrast of the %s theme', (_name, tokens) => {
  it.each(pairs(tokens))('%s reaches 4.5:1', (_label, fg, bg) => {
    expect(contrastRatio(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(4.5)
  })
})

describe('light theme completeness', () => {
  it('redefines every semantic color the dark theme declares, except the solid state colors', () => {
    const lightOnly = vars(block(/\[data-theme="light"\]\s*\{/))
    const missing = Object.keys(dark).filter(
      (k) => !(k in lightOnly) && !/^status-[a-z_]+$/.test(k),
    )
    expect(missing).toEqual([])
  })
})
