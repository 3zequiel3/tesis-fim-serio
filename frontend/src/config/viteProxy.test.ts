// @vitest-environment node

import { describe, expect, it } from 'vitest'
import viteConfig from '../../vite.config'

describe('development refresh proxy', () => {
  it('exposes the exact same-origin path required by the scoped cookie', () => {
    const config = viteConfig as { server?: { proxy?: Record<string, unknown> } }
    expect(Object.keys(config.server?.proxy ?? {})).toContain('/auth/refresh')
    expect(config.server?.proxy?.['/api/auth/refresh']).toBeUndefined()
  })
})
