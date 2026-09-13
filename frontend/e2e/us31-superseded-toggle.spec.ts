import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import {
  cleanupLoginFixtures,
  cleanupSupersededFixture,
  createSupersededFixture,
  login,
  type SupersededFixture,
  writeSanitizedEvidence,
} from './helpers'

test.afterEach(() => cleanupLoginFixtures())

test('US-31 oculta superseded por defecto, togglea, persiste URL y consulta backend real', async ({ page }) => {
  let fixture: SupersededFixture | undefined
  const listRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/events?')) listRequests.push(request.url())
  })

  try {
    fixture = createSupersededFixture(`us31-toggle-${randomUUID()}`)
    await login(page)
    await page.goto(`/events?path_prefix=${encodeURIComponent(fixture.path)}`)
    await expect(page.getByRole('link', { name: fixture.path })).toHaveCount(1)
    await expect(page.getByText('superseded', { exact: true })).toHaveCount(0)

    const includeRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return url.pathname.endsWith('/api/events') && url.searchParams.get('include_superseded') === 'true'
    })
    await page.getByRole('checkbox', { name: 'Mostrar eventos superseded' }).click()
    await includeRequest
    await expect(page).toHaveURL(/include_superseded=true/)
    await expect(page.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
    await expect(page.getByRole('link', { name: fixture.path })).toHaveCount(3)

    await page.reload()
    await expect(page.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
    await expect(page.getByRole('link', { name: fixture.path })).toHaveCount(3)
    expect(listRequests.some((requestUrl) => new URL(requestUrl).searchParams.get('include_superseded') === 'true')).toBe(true)
  } finally {
    if (fixture) cleanupSupersededFixture(fixture)
  }
})

test('US-31 muestra vínculo e identificador parent_event_id de forma visible', async ({ page }, testInfo) => {
  let fixture: SupersededFixture | undefined
  try {
    fixture = createSupersededFixture(`us31-parent-${randomUUID()}`)
    await login(page)
    await page.goto(`/events?path_prefix=${encodeURIComponent(fixture.path)}&include_superseded=true`)
    const supersededRow = page.getByRole('row').filter({
      has: page.getByRole('checkbox', { name: `Seleccionar evento #${fixture.superseded_id}` }),
    })
    await expect(supersededRow).toBeVisible()
    const chainLink = supersededRow.getByRole('link', { name: 'Evento superseded, ver cadena' })
    await expect(chainLink).toHaveAttribute('href', `/events/${fixture.parent_id}`)
    await expect(chainLink).toHaveAttribute('title', `Ver evento padre #${fixture.parent_id}`)

    const evidence = {
      expected_visible_text: `#${fixture.parent_id}`,
      visible_text: (await chainLink.innerText()).trim(),
      actual_title: await chainLink.getAttribute('title'),
      source: 'frontend/src/components/ui/EventsTable.tsx',
    }
    writeSanitizedEvidence('parent-id-rendering.json', evidence)
    await testInfo.attach('parent-id-rendering.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    })

    await expect(supersededRow.getByText(`#${fixture.parent_id}`, { exact: true })).toBeVisible()
  } finally {
    if (fixture) cleanupSupersededFixture(fixture)
  }
})
