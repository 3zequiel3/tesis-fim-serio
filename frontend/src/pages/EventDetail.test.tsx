import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'
import { EventDetail } from './EventDetail'
import type { EventDetail as EventDetailData } from '@/api/events'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function makeEvent(overrides: Partial<EventDetailData> = {}): EventDetailData {
  return {
    id: 42,
    path: '/etc/passwd',
    hash_detected: 'deadbeef',
    hash_expected: null,
    diff_text: null,
    status: 'pending',
    severity: 'low',
    parent_event_id: null,
    version: 0,
    process_pid: null,
    process_uid: null,
    process_exe: null,
    detected_at: '2026-08-20T12:00:00Z',
    received_at: '2026-08-20T12:00:00Z',
    created_at: '2026-08-20T12:00:00Z',
    resolved_at: null,
    resolved_by: null,
    ack_status: null,
    is_symlink: false,
    symlink_target: null,
    action_failed: false,
    action_error: null,
    ...overrides,
  }
}

function renderDetail(id: number) {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:id" element={<EventDetail />} />
    </Routes>,
    { route: `/events/${id}` }
  )
}

describe('EventDetail content diff', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('renders the textual unified diff returned by the detail API', async () => {
    apiGet.mockResolvedValue({ data: makeEvent({ diff_text: '--- a/etc/hosts\n+++ b/etc/hosts\n@@ -1 +1 @@\n-old value\n+new value\n' }) })
    renderDetail(10)
    const viewer = await screen.findByTestId('content-diff')
    expect(viewer).toHaveTextContent('old value')
    expect(viewer).toHaveTextContent('new value')
  })

  it('does not present hashes as a content diff when text is unavailable', async () => {
    apiGet.mockResolvedValue({ data: makeEvent({ hash_expected: 'expected', diff_text: null }) })
    renderDetail(11)
    expect(await screen.findByText('Diff textual no disponible para este evento.')).toBeInTheDocument()
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })
})
