import { test, expect, type Request } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import {
  assertExternalNotificationChannelsEmpty,
  cleanupLoginFixtures,
  cleanupRealtimeFixture,
  createRealtimeFixture,
  login,
  probeRealtimeEvent,
  publishRealtimeEvent,
  startSseProxyService,
  stopSseProxyService,
  type RealtimeFixture,
  writeSanitizedEvidence,
} from './helpers'

test.afterEach(() => cleanupLoginFixtures())

test('US-20 consumer real crea Alert y SSE muestra toast sin reload', async ({ page }, testInfo) => {
  assertExternalNotificationChannelsEmpty()
  const prefix = `us20-chain-${randomUUID()}`
  let fixture: RealtimeFixture | undefined
  const streamRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/alerts/stream?token=')) streamRequests.push(request.url())
  })

  try {
    fixture = createRealtimeFixture(prefix)
    await login(page)
    await expect.poll(() => streamRequests.length).toBeGreaterThanOrEqual(1)
    await page.waitForTimeout(1_000)

    const published = publishRealtimeEvent(fixture, `/fim-e2e/${prefix}-event.txt`)
    await expect.poll(() => probeRealtimeEvent(published.event_uuid), { timeout: 12_000 }).toMatchObject({
      severity: 'high',
      channel: 'log_only',
      delivered: true,
    })
    const probe = probeRealtimeEvent(published.event_uuid)
    expect(probe.event_id).not.toBeNull()
    expect(probe.alert_id).not.toBeNull()
    await expect(page.getByText(`Alerta high — evento #${probe.event_id}`)).toBeVisible()

    const evidence = {
      external_channels: 'empty',
      native_event_source_requests: streamRequests.length,
      probe,
      page_reloaded: false,
    }
    writeSanitizedEvidence('sse-chain.json', evidence)
    await testInfo.attach('sse-chain.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    })
  } finally {
    if (fixture) {
      const cleanup = cleanupRealtimeFixture(fixture)
      await testInfo.attach('cleanup-sanitized.json', {
        body: JSON.stringify(cleanup, null, 2),
        contentType: 'application/json',
      })
    }
  }
})

test('US-20 EventSource reconecta tras un corte real sólo de la ruta SSE y recibe un evento nuevo', async ({ page }, testInfo) => {
  assertExternalNotificationChannelsEmpty()
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Network.enable')
  const prefix = `us20-reconnect-${randomUUID()}`
  let fixture: RealtimeFixture | undefined
  let sseProxyStopped = false
  const streamRequests: string[] = []
  const successfulStreamResponses: number[] = []
  let initialStreamRequest: Request | undefined
  page.on('request', (request) => {
    if (request.url().includes('/api/alerts/stream?token=')) {
      streamRequests.push(request.url())
      initialStreamRequest ??= request
    }
  })
  cdp.on('Network.responseReceived', (event: { response: { url: string; status: number } }) => {
    if (event.response.url.includes('/api/alerts/stream?token=') && event.response.status === 200) {
      successfulStreamResponses.push(event.response.status)
    }
  })

  try {
    fixture = createRealtimeFixture(prefix)
    await login(page)
    await expect.poll(() => streamRequests.length).toBeGreaterThanOrEqual(1)
    await expect.poll(() => successfulStreamResponses.length).toBeGreaterThanOrEqual(1)
    const first = publishRealtimeEvent(fixture, `/fim-e2e/${prefix}-first.txt`)
    await expect.poll(() => probeRealtimeEvent(first.event_uuid), { timeout: 12_000 }).toMatchObject({ delivered: true })
    const firstProbe = probeRealtimeEvent(first.event_uuid)
    await expect(page.getByText(`Alerta high — evento #${firstProbe.event_id}`)).toBeVisible()
    const requestsBeforeInterruption = streamRequests.length

    expect(initialStreamRequest).toBeDefined()
    const streamClosed = new Promise<{ outcome: 'failed' | 'finished'; error: string | null }>((resolve, reject) => {
      const timeout = setTimeout(() => {
        cleanup()
        reject(new Error('the original SSE request did not close after stopping the isolated SSE proxy'))
      }, 12_000)
      const cleanup = () => {
        clearTimeout(timeout)
        page.off('requestfailed', onFailed)
        page.off('requestfinished', onFinished)
      }
      const onFailed = (request: Request) => {
        if (request !== initialStreamRequest) return
        cleanup()
        resolve({ outcome: 'failed', error: request.failure()?.errorText ?? null })
      }
      const onFinished = (request: Request) => {
        if (request !== initialStreamRequest) return
        cleanup()
        resolve({ outcome: 'finished', error: null })
      }
      page.on('requestfailed', onFailed)
      page.on('requestfinished', onFinished)
    })
    stopSseProxyService()
    sseProxyStopped = true
    const closure = await streamClosed

    // The fault boundary must affect only SSE. Both the ordinary API route and
    // the real scoped refresh endpoint remain available through frontend nginx.
    expect((await page.request.get('/api/health')).status()).toBe(200)
    expect((await page.request.post('/auth/refresh')).status()).toBe(200)

    startSseProxyService()
    sseProxyStopped = false
    await expect.poll(() => streamRequests.length, { timeout: 30_000 }).toBeGreaterThan(requestsBeforeInterruption)

    // A new request can be issued while nginx still returns 502. A successful
    // second SSE response is the unambiguous transport-ready boundary: headers
    // and the first keepalive have crossed the real proxy/backend connection.
    // Do not publish the acceptance event until that boundary is observed.
    await expect.poll(() => successfulStreamResponses.length, { timeout: 60_000 }).toBeGreaterThanOrEqual(2)
    const successfulResponsesBeforePublish = successfulStreamResponses.length

    const afterReconnect = publishRealtimeEvent(fixture, `/fim-e2e/${prefix}-after-reconnect.txt`)
    await expect.poll(() => probeRealtimeEvent(afterReconnect.event_uuid), { timeout: 12_000 }).toMatchObject({ delivered: true })
    const receivedProbe = probeRealtimeEvent(afterReconnect.event_uuid)
    await expect(page.getByText(`Alerta high — evento #${receivedProbe.event_id}`)).toBeVisible()

    const evidence = {
      transport: 'real stop/start of an isolated lab-only SSE proxy; backend and auth remained available',
      original_stream_closed_as: closure.outcome,
      stream_close_error: closure.error,
      api_during_sse_cut_status: 200,
      refresh_during_sse_cut_status: 200,
      requests_before_interruption: requestsBeforeInterruption,
      requests_observed_at_attachment: streamRequests.length,
      successful_stream_responses: successfulStreamResponses.length,
      successful_responses_before_publish: successfulResponsesBeforePublish,
      events_published_after_transport_ready: 1,
      received_event_id: receivedProbe.event_id,
    }
    writeSanitizedEvidence('sse-reconnect.json', evidence)
    await testInfo.attach('sse-reconnect.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    })
  } finally {
    if (sseProxyStopped) startSseProxyService()
    if (fixture) cleanupRealtimeFixture(fixture)
    await cdp.detach()
  }
})
