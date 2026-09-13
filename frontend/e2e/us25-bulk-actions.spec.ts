import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { cleanupBulkFixture, cleanupLoginFixtures, createBulkFixture, login, probeBulkFixture, type BulkFixture } from './helpers'

test.afterEach(() => cleanupLoginFixtures())

test('US-25 selección, modal y respuesta parcial contra backend/DB/Valkey reales', async ({ page }, testInfo) => {
  const prefix = `fim-e2e-us25-${randomUUID()}`
  let fixture: BulkFixture | undefined
  let bulkRequests = 0
  page.on('request', (request) => {
    if (request.url().includes('/api/actions/bulk-')) bulkRequests += 1
  })

  try {
    fixture = createBulkFixture(prefix)
    const loginResponse = await login(page)
    const accessToken = ((await loginResponse.json()) as { access_token: string }).access_token
    const eventsResponse = page.waitForResponse((response) => response.url().includes('/api/events?'))
    await page.goto(`/events?status=pending&path_prefix=${encodeURIComponent(`/watch/${prefix}`)}`)
    expect((await eventsResponse).status()).toBe(200)
    await expect(page.getByRole('heading', { name: 'Eventos' })).toBeVisible()

    const rowCheckboxes = page.getByRole('checkbox', { name: /Seleccionar evento #/ })
    await expect(rowCheckboxes).toHaveCount(12)
    await rowCheckboxes.first().check()
    await expect(page.getByText('1 evento seleccionado')).toBeVisible()
    await rowCheckboxes.first().uncheck()
    await page.getByRole('checkbox', { name: 'Seleccionar todos en la página' }).check()
    await expect(page.getByText('12 eventos seleccionados')).toBeVisible()

    await page.getByRole('button', { name: 'Rechazar seleccionados' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Se van a rechazar 12 eventos')
    for (const path of fixture.paths.slice().reverse().slice(0, 10)) await expect(dialog).toContainText(path)
    await expect(dialog).toContainText('... y 2 más')
    await dialog.getByRole('button', { name: 'Cancelar' }).click()
    expect(bulkRequests).toBe(0)

    const preResolve = await page.request.post('/api/actions/reject', {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { event_id: fixture.ids.at(-1), version: 0, action: 'restore' },
    })
    expect(preResolve.status()).toBe(200)
    await page.getByRole('button', { name: 'Rechazar seleccionados' }).click()
    await dialog.getByLabel('Restaurar archivo').check()
    const bulkResponsePromise = page.waitForResponse((response) => response.url().endsWith('/api/actions/bulk-reject'))
    await dialog.getByRole('button', { name: 'Rechazar', exact: true }).click()
    const bulkResponse = await bulkResponsePromise
    expect(bulkResponse.status()).toBe(200)
    const body = await bulkResponse.json() as { succeeded: number[]; failed: Array<{ event_id: number; reason: string }> }
    expect(body.succeeded).toHaveLength(11)
    expect(body.failed).toEqual([{ event_id: fixture.ids.at(-1), reason: 'not_pending' }])

    const requestBody = bulkResponse.request().postDataJSON() as Record<string, unknown>
    await testInfo.attach('wire-contract-sanitized.json', {
      body: JSON.stringify({
        request_top_level_keys: Object.keys(requestBody).sort(),
        event_ids_count: (requestBody.event_ids as number[]).length,
        action: requestBody.action,
        response_top_level_keys: Object.keys(body).sort(),
        succeeded_count: body.succeeded.length,
        failed: body.failed,
      }, null, 2),
      contentType: 'application/json',
    })

    await expect(page.getByText('Resultado: 11 rechazados, 1 fallidos')).toBeVisible()
    await page.getByRole('button', { name: 'Ver detalle del resultado' }).click()
    for (const path of fixture.paths.slice(0, 11)) {
      const row = page.getByRole('listitem').filter({ hasText: path })
      await expect(row).toContainText('Correcto')
    }
    const failedRow = page.getByRole('listitem').filter({ hasText: fixture.paths.at(-1)! })
    await expect(failedRow).toContainText('Falló: not_pending')

    await expect(rowCheckboxes).toHaveCount(0)
    await expect(page.getByText('1 evento seleccionado')).toBeVisible()
    const probe = probeBulkFixture(fixture)
    expect(probe).toEqual({ pending: 0, rejected: 12, audit_count: 12, command_count: 0 })
    await testInfo.attach('integration-probe-sanitized.json', {
      body: JSON.stringify({ ...probe, agent_id_hash: prefix.length > 0 ? 'present-redacted' : 'missing', note: 'baseline-absent fixtures intentionally produce no command per RN-74' }, null, 2),
      contentType: 'application/json',
    })

    await test.step('valida wire canónico y rechazo explícito de items legacy', async () => {
      expect(requestBody).toEqual({ event_ids: fixture!.ids, action: 'restore' })
      expect(Object.keys(body).sort()).toEqual(['failed', 'succeeded'])
      const legacy = await page.request.post('/api/actions/bulk-reject', {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { items: [{ event_id: fixture!.ids[0], version: 0, action: 'restore' }] },
      })
      expect(legacy.status()).toBe(422)
    })

  } finally {
    if (fixture) cleanupBulkFixture(fixture)
  }
})
