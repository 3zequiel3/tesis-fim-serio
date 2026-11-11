import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ThemeToggle } from '@/components/ui/ThemeToggle'

const themeInit = readFileSync(resolve(__dirname, '../../public/theme-init.js'), 'utf8')

function mockSystemScheme(scheme: 'light' | 'dark') {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('light') ? scheme === 'light' : scheme === 'dark',
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

function runThemeInit() {
  // The same file index.html loads before the first paint.
  new Function(themeInit)()
}

describe('theme-init.js', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('follows prefers-color-scheme when no theme was saved', () => {
    mockSystemScheme('light')
    runThemeInit()
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('falls back to dark when the system prefers dark', () => {
    mockSystemScheme('dark')
    runThemeInit()
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('a saved choice wins over the system preference', () => {
    mockSystemScheme('light')
    localStorage.setItem('fim.theme', 'dark')
    runThemeInit()
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })
})

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    mockSystemScheme('light')
    document.documentElement.setAttribute('data-theme', 'light')
  })
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme')
  })

  it('switches the theme and persists the choice across a reload', async () => {
    render(<ThemeToggle />)
    await userEvent.click(screen.getByRole('button', { name: /tema oscuro/i }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(localStorage.getItem('fim.theme')).toBe('dark')

    // "Reload": the system still prefers light, the saved choice must win.
    document.documentElement.removeAttribute('data-theme')
    act(() => runThemeInit())
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })
})
