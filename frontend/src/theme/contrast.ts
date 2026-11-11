// WCAG 2.x contrast helpers, used by the token contrast test (task 2.2).

export function parseHex(hex: string): [number, number, number] {
  const h = hex.trim().replace(/^#/, '')
  if (!/^[0-9a-fA-F]{6}$/.test(h)) throw new Error(`Not a 6-digit hex color: ${hex}`)
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as [number, number, number]
}

function linear(channel: number): number {
  return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number {
  const [r, g, b] = parseHex(hex).map(linear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
