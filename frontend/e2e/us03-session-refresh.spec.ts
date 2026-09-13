import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { cleanupLoginFixtures, login } from './helpers'

test.afterEach(() => cleanupLoginFixtures())

function jwtExpirationMs(token: string): number {
  const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8')) as { exp: number }
  return payload.exp * 1000
}

function fingerprint(value: string): string {
  return createHash('sha256').update(value).digest('hex')
}

test('US-03 refresh anticipado, revocación y contrato de cookie con servicios reales', async ({ page }, testInfo) => {
  await page.clock.install()
  const refreshResponses: number[] = []
  let activeAccess = ''
  let predecessorRefresh = ''
  page.on('response', async (response) => {
    if (!response.url().endsWith('/auth/refresh')) return
    refreshResponses.push(response.status())
    if (response.status() === 200) {
      try {
        const body = await response.json() as { access_token: string }
        activeAccess = body.access_token
      } catch {
        // A closing context may cancel a response body after the verdict exists.
      }
    }
  })

  await test.step('login real y refresh anticipado exactamente una vez', async () => {
    const response = await login(page)
    const loginBody = await response.json() as { access_token: string }
    const initialAccess = loginBody.access_token
    const initialCookie = (await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token')
    expect(initialCookie).toBeDefined()
    predecessorRefresh = initialCookie!.value

    await page.goto('/events?status=pending')
    await expect(page.getByRole('heading', { name: 'Eventos' })).toBeVisible()
    const delay = Math.max(0, jwtExpirationMs(initialAccess) - Date.now() - 60_000 + 250)
    await page.clock.fastForward(delay)
    await expect.poll(() => refreshResponses.filter((status) => status === 200).length).toBe(1)
    await expect.poll(() => activeAccess.length).toBeGreaterThan(0)

    const currentCookie = (await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token')
    expect(currentCookie).toBeDefined()
    expect(fingerprint(currentCookie!.value)).not.toBe(fingerprint(initialCookie!.value))
    await expect(page).toHaveURL(/\/events\?status=pending$/)
    await expect(page.getByRole('heading', { name: 'Eventos' })).toBeVisible()
    await page.clock.fastForward(1_000)
    expect(refreshResponses.filter((status) => status === 200), 'no refresh loop').toHaveLength(1)
    await page.clock.setFixedTime(new Date())

    const actualCookieContract = {
      httpOnly: currentCookie!.httpOnly,
      secure: currentCookie!.secure,
      sameSite: currentCookie!.sameSite,
      path: currentCookie!.path,
    }
    await testInfo.attach('cookie-contract-sanitized.json', {
      body: JSON.stringify({ actual: actualCookieContract, canonical: { httpOnly: true, sameSite: 'Strict', path: '/auth/refresh' } }, null, 2),
      contentType: 'application/json',
    })
    expect(actualCookieContract).toEqual({ httpOnly: true, secure: false, sameSite: 'Strict', path: '/auth/refresh' })
  })

  await test.step('revocación real limpia la sesión, reemplaza historial y Back no revela la vista', async () => {
    expect(activeAccess).not.toBe('')
    const bearerRequestPromise = page.waitForRequest((request) => request.url().includes('/api/events') && request.url().includes('severity=critical'))
    const bearerResponsePromise = page.waitForResponse((response) => response.url().includes('/api/events') && response.url().includes('severity=critical'))
    await page.getByLabel('critical').click()
    const bearerHeader = (await bearerRequestPromise).headers()['authorization']
    expect(bearerHeader).toMatch(/^Bearer /)
    activeAccess = bearerHeader.replace(/^Bearer /, '')
    expect((await bearerResponsePromise).status()).toBe(200)
    const refreshBeforeLogout = (await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token')
    expect(refreshBeforeLogout?.path).toBe('/auth/refresh')
    const logoutResponse = await page.request.post('/api/auth/logout', {
      headers: { Authorization: `Bearer ${activeAccess}` },
    })
    expect(logoutResponse.status()).toBe(200)
    const refreshReuse = await page.request.post('/auth/refresh', {
      headers: { Cookie: `refresh_token=${refreshBeforeLogout!.value}` },
    })
    expect(refreshReuse.status()).toBe(401)
    const predecessorReuse = await page.request.post('/auth/refresh', {
      headers: { Cookie: `refresh_token=${predecessorRefresh}` },
    })
    expect(predecessorReuse.status()).toBe(401)
    const revokedProbe = await page.request.get('/api/events', {
      headers: { Authorization: `Bearer ${activeAccess}` },
    })
    expect(revokedProbe.status()).toBe(401)

    const loginTransitionsBefore = refreshResponses.filter((status) => status === 401).length
    const protectedResponse = page.waitForResponse((response) => response.url().includes('/api/events') && response.status() === 401)
    await page.getByLabel('pending').click()
    await protectedResponse
    await expect.poll(() => refreshResponses.filter((status) => status === 401).length - loginTransitionsBefore).toBe(1)
    await expect.soft(page).toHaveURL(/\/login$/, { timeout: 3_000 })
    expect(refreshResponses.filter((status) => status === 401).length - loginTransitionsBefore).toBe(1)
    if (page.url().endsWith('/login')) {
      await page.goBack()
      await expect.soft(page).toHaveURL(/\/login$/)
      await expect.soft(page.getByRole('heading', { name: 'Eventos' })).toHaveCount(0)
    } else {
      await testInfo.attach('navigation-defect-sanitized.json', {
        body: JSON.stringify({ expected: '/login', actual_path: new URL(page.url()).pathname, refresh_401_count: 1 }, null, 2),
        contentType: 'application/json',
      })
    }
  })

  await test.step('confirma limpieza de la cookie canónica y de la ruta legacy', async () => {
    const cookies = (await page.context().cookies()).filter((item) => item.name === 'refresh_token')
    expect(cookies).toHaveLength(0)
  })
})
