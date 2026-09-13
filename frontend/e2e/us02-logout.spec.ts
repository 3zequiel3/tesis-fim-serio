import { test, expect } from '@playwright/test'
import { cleanupLoginFixtures, login, writeSanitizedEvidence } from './helpers'

test.afterEach(() => cleanupLoginFixtures())

test('US-02 logout revoca la sesión real, borra cookie y Back no reabre la vista protegida', async ({ page }, testInfo) => {
  await login(page)
  const eventsRequestPromise = page.waitForRequest((request) => request.url().includes('/api/events?status=pending'))
  await page.goto('/events?status=pending')
  const eventsRequest = await eventsRequestPromise
  const accessToken = eventsRequest.headers()['authorization']?.replace(/^Bearer /, '') ?? ''
  expect(accessToken).not.toBe('')
  await expect(page.getByRole('heading', { name: 'Eventos' })).toBeVisible()

  const logoutResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/logout') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  const logoutStatus = (await logoutResponsePromise).status()
  await expect(page).toHaveURL(/\/login$/)
  const refreshCookiePresent = Boolean((await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token'))

  await page.goBack()
  await page.waitForTimeout(1_000)
  const backPath = new URL(page.url()).pathname

  const accessProbe = await page.request.get('/api/events', {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const refreshProbe = await page.request.post('/api/auth/refresh')

  const evidence = {
    logout_status: logoutStatus,
    refresh_cookie_present_after_logout: refreshCookiePresent,
    active_access_probe_status: accessProbe.status(),
    refresh_probe_status: refreshProbe.status(),
    back_path: backPath,
  }
  writeSanitizedEvidence('logout-contract.json', evidence)
  await testInfo.attach('logout-contract.json', {
    body: JSON.stringify(evidence, null, 2),
    contentType: 'application/json',
  })
  expect.soft(logoutStatus, 'backend logout must accept the authenticated browser request').toBe(200)
  expect.soft(refreshCookiePresent, 'refresh cookie must be cleared').toBe(false)
  expect.soft(accessProbe.status(), 'active access token must be revoked').toBe(401)
  expect.soft(refreshProbe.status(), 'refresh token must be revoked').toBe(401)
  expect.soft(backPath, 'Back must not reopen a protected view').toBe('/login')
})
