import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { bulkApprove, bulkReject, type RejectAction } from './actions'
import { installRequestCapture, type RequestCapture } from '@/test/captureRequest'

const FIXTURE_PATH = path.resolve(process.cwd(), '..', 'contracts', 'actions.bulk-reject.request.json')
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as {
  event_ids: number[]
  action: RejectAction
}

let capture: RequestCapture | undefined
afterEach(() => { capture?.restore(); capture = undefined })

describe('bulk actions — canonical event_ids wire contract', () => {
  it('serializes bulk reject exactly as the shared canonical fixture', async () => {
    capture = installRequestCapture()
    await bulkReject(fixture.event_ids, fixture.action)
    expect(capture.requests).toHaveLength(1)
    expect(capture.last()!.url).toBe('/actions/bulk-reject')
    expect(JSON.parse(capture.last()!.data as string)).toEqual(fixture)
  })

  it('serializes bulk approve with event_ids only', async () => {
    capture = installRequestCapture()
    await bulkApprove([10, 20])
    expect(JSON.parse(capture.last()!.data as string)).toEqual({ event_ids: [10, 20] })
  })

  it('does not emit the legacy items/version representation', async () => {
    capture = installRequestCapture()
    await bulkReject(fixture.event_ids, fixture.action)
    const body = JSON.parse(capture.last()!.data as string)
    expect(body.items).toBeUndefined()
    expect(body.version).toBeUndefined()
    expect(body.confirm_absent).toBeUndefined()
    expect(body.baseline_absent).toBeUndefined()
  })
})
