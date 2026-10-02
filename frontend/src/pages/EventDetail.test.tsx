import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'
import { EventDetail } from './EventDetail'
import type { EventDetail as EventDetailData } from '@/api/events'

// D51/RN-145 (D-10 del design, task 11.6): el detalle de un evento sin ruta
// sustituye la fila de path por el tipo de evento y su causa, sin romper al
// renderizar. Mismo mock de @/api/client que Events.test.tsx.

const { apiGet, apiPost, toastError, toastSuccess, toastInfo } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))

vi.mock('sonner', () => ({
  toast: { error: toastError, success: toastSuccess, info: toastInfo, warning: vi.fn() },
}))

function makeEvent(overrides: Partial<EventDetailData> = {}): EventDetailData {
  return {
    id: 42,
    event_type: 'file_modified',
    path: '/etc/passwd',
    hash_detected: 'deadbeef',
    hash_expected: null,
    diff_text: null,
    is_binary: false,
    hex_dump_before: null,
    hex_dump_after: null,
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
    action_type: 'manual_review',
    ...overrides,
  }
}

/** Respuesta por defecto para GET /events/{id}/chain — cadena de un solo evento (US-10). */
function makeChainResponse(overrides: { path?: string | null; items?: unknown[] } = {}) {
  return { path: overrides.path ?? '/etc/passwd', items: overrides.items ?? [] }
}

/** Enruta apiGet según la URL: /chain va a la cadena, cualquier otra al detalle. */
function mockDetailAndChain(
  event: EventDetailData,
  chain: ReturnType<typeof makeChainResponse> = makeChainResponse()
) {
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/chain')) return Promise.resolve({ data: chain })
    return Promise.resolve({ data: event })
  })
}

function renderDetail(id: number) {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:id" element={<EventDetail />} />
    </Routes>,
    { route: `/events/${id}` }
  )
}

describe('EventDetail — evento sin ruta (D51/RN-145)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('el detalle de un evento sin ruta muestra el tipo de evento y su causa, no rompe al renderizar', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({ id: 7, path: null, event_type: 'detection_gap' }),
    })

    renderDetail(7)

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(await screen.findByText('Brecha de detección')).toBeInTheDocument()
    expect(screen.getByText(/desbordó su cola de eventos fanotify/)).toBeInTheDocument()
  })

  it('el detalle de un evento sin ruta omite el bloque de contexto de proceso cuando los tres campos son nulos', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 8,
        path: null,
        event_type: 'detection_gap',
        process_pid: null,
        process_uid: null,
        process_exe: null,
      }),
    })

    renderDetail(8)

    await screen.findByText('Brecha de detección')
    expect(screen.queryByText('Proceso que generó el evento')).not.toBeInTheDocument()
  })

  it('el detalle de un evento con ruta renderiza igual que antes (no regresión)', async () => {
    apiGet.mockResolvedValue({ data: makeEvent({ id: 9, path: '/etc/hosts' }) })

    renderDetail(9)

    expect(await screen.findByText('/etc/hosts')).toBeInTheDocument()
    expect(screen.queryByText('Brecha de detección')).not.toBeInTheDocument()
  })

  it('renderiza el diff textual real recibido por la API', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 10,
        diff_text: '--- a/etc/hosts\n+++ b/etc/hosts\n@@ -1 +1 @@\n-old value\n+new value\n',
      }),
    })

    renderDetail(10)

    const viewer = await screen.findByTestId('content-diff')
    expect(viewer).toHaveTextContent('old value')
    expect(viewer).toHaveTextContent('new value')
  })

  it('declara la ausencia sin presentar hashes como diff', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({ id: 11, hash_expected: 'expected', diff_text: null }),
    })

    renderDetail(11)

    expect(await screen.findByText('Diff textual no disponible para este evento.')).toBeInTheDocument()
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })

  it('muestra comparación de hashes y hex dump para un evento binario', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 12,
        diff_text: null,
        is_binary: true,
        hash_expected: 'aaaa',
        hash_detected: 'bbbb',
        hex_dump_before: '00000000  89 50 4e 47',
        hex_dump_after: '00000000  ff ee dd cc',
      }),
    })

    renderDetail(12)

    const binaryView = await screen.findByTestId('binary-diff')
    expect(binaryView).toHaveTextContent('89 50 4e 47')
    expect(binaryView).toHaveTextContent('ff ee dd cc')
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })
})

describe('EventDetail — badge de cuarentena (D82/RN-176)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('un evento rejected con quarantine_state quarantined muestra el badge junto al de status', async () => {
    mockDetailAndChain(makeEvent({ status: 'rejected', quarantine_state: 'quarantined' }))

    renderDetail(42)

    const badge = await screen.findByTestId('quarantine-state-badge')
    expect(badge).toHaveTextContent('quarantined')
    // El status del evento sigue siendo rejected: la cuarentena no es un estado suyo.
    expect(screen.getAllByText('rejected').length).toBeGreaterThan(0)
  })

  it('none o el campo ausente no muestran el badge', async () => {
    mockDetailAndChain(makeEvent({ quarantine_state: 'none' }))

    renderDetail(42)

    await screen.findByText('/etc/passwd')
    expect(screen.queryByTestId('quarantine-state-badge')).not.toBeInTheDocument()
  })
})

describe('EventDetail — US-08 (tipo de acción, severidad, fecha de creación, cadena)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('muestra el tipo de acción, la severidad y la fecha de creación', async () => {
    mockDetailAndChain(
      makeEvent({ id: 12, action_type: 'auto_restore', severity: 'critical', created_at: '2026-08-20T10:00:00Z' })
    )

    renderDetail(12)

    expect(await screen.findByText('auto_restore')).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('Fecha de creación')).toBeInTheDocument()
  })

  it('si el evento tiene parent_event_id, muestra un enlace al evento padre', async () => {
    mockDetailAndChain(makeEvent({ id: 13, parent_event_id: 5 }))

    renderDetail(13)

    const parentLink = await screen.findByRole('link', { name: /evento padre/i })
    expect(parentLink).toHaveAttribute('href', '/events/5')
  })

  it('sin parent_event_id no muestra enlace al evento padre', async () => {
    mockDetailAndChain(makeEvent({ id: 14, parent_event_id: null }))

    renderDetail(14)

    await screen.findByText('/etc/passwd')
    expect(screen.queryByRole('link', { name: /evento padre/i })).not.toBeInTheDocument()
  })

  it('si el evento pertenece a una cadena de más de un elemento, indica su posición y permite navegar a la cadena (US-10)', async () => {
    mockDetailAndChain(
      makeEvent({ id: 20, path: '/etc/passwd' }),
      makeChainResponse({
        path: '/etc/passwd',
        items: [{ id: 18 }, { id: 20 }, { id: 21 }],
      })
    )

    renderDetail(20)

    expect(await screen.findByText(/posici[oó]n 2 de 3/i)).toBeInTheDocument()
    const chainLink = screen.getByRole('link', { name: /ver cadena/i })
    expect(chainLink).toHaveAttribute('href', '/events/20/chain')
  })

  it('si la cadena tiene un solo evento, no muestra el indicador de posición', async () => {
    mockDetailAndChain(
      makeEvent({ id: 30, path: '/etc/passwd' }),
      makeChainResponse({ path: '/etc/passwd', items: [{ id: 30 }] })
    )

    renderDetail(30)

    await screen.findByText('/etc/passwd')
    expect(screen.queryByText(/posici[oó]n/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /ver cadena/i })).not.toBeInTheDocument()
  })

  it('un evento sin path (detection_gap) no dispara la consulta de cadena', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url.includes('/chain')) {
        throw new Error('no debería consultarse la cadena para un evento sin path')
      }
      return Promise.resolve({ data: makeEvent({ id: 40, path: null, event_type: 'detection_gap' }) })
    })

    renderDetail(40)

    expect(await screen.findByText('Brecha de detección')).toBeInTheDocument()
    expect(screen.queryByText(/posici[oó]n/i)).not.toBeInTheDocument()
  })
})

// US-11: toast ante 409 (compartido por approve y reject) y aviso de archivo
// ausente ante 422 en approve, con los textos literales de la historia.

function axiosErrorWithStatus(status: number, data: Record<string, unknown> = {}) {
  return Object.assign(new Error('request failed'), {
    isAxiosError: true,
    response: { status, data },
  })
}

describe('EventDetail — US-11 (toast 409 y aviso de archivo ausente)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    toastError.mockReset()
    toastSuccess.mockReset()
    toastInfo.mockReset()
  })

  it('el detalle de un evento pending muestra los botones Aprobar y Rechazar', async () => {
    mockDetailAndChain(makeEvent({ id: 50, status: 'pending' }))

    renderDetail(50)

    expect(await screen.findByRole('button', { name: 'Aprobar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rechazar' })).toBeInTheDocument()
  })

  it('approve con 409 muestra el toast literal e invalida las queries del evento y la lista', async () => {
    mockDetailAndChain(makeEvent({ id: 51, status: 'pending' }))
    apiPost.mockRejectedValue(axiosErrorWithStatus(409))
    const user = userEvent.setup()

    const { queryClient } = renderDetail(51)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: 'Aprobar' }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        'Este evento ya fue resuelto o reemplazado. Refrescando lista...'
      )
    )
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['event', 51] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['events'] })
  })

  it('reject con 409 muestra el mismo toast e invalida las queries', async () => {
    mockDetailAndChain(makeEvent({ id: 52, status: 'pending' }))
    apiPost.mockRejectedValue(axiosErrorWithStatus(409))
    const user = userEvent.setup()

    const { queryClient } = renderDetail(52)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: 'Rechazar' }))
    await user.click(await screen.findByRole('button', { name: 'Confirmar rechazo' }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        'Este evento ya fue resuelto o reemplazado. Refrescando lista...'
      )
    )
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['event', 52] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['events'] })
  })

  it('approve con 422 absent_confirmation_required muestra el aviso literal; Confirmar reenvía con confirm_absent:true', async () => {
    mockDetailAndChain(makeEvent({ id: 53, status: 'pending', version: 3 }))
    apiPost.mockRejectedValueOnce(
      axiosErrorWithStatus(422, { code: 'absent_confirmation_required' })
    )
    const user = userEvent.setup()

    renderDetail(53)

    await user.click(await screen.findByRole('button', { name: 'Aprobar' }))

    expect(
      await screen.findByText(
        'El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.'
      )
    ).toBeInTheDocument()

    apiPost.mockResolvedValueOnce({ data: {} })
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() =>
      expect(apiPost).toHaveBeenLastCalledWith('/actions/approve', {
        event_id: 53,
        version: 3,
        confirm_absent: true,
      })
    )
  })

  it('Cancelar oculta el aviso de archivo ausente sin enviar una nueva request', async () => {
    mockDetailAndChain(makeEvent({ id: 54, status: 'pending' }))
    apiPost.mockRejectedValueOnce(
      axiosErrorWithStatus(422, { code: 'absent_confirmation_required' })
    )
    const user = userEvent.setup()

    renderDetail(54)

    await user.click(await screen.findByRole('button', { name: 'Aprobar' }))
    await screen.findByText(
      'El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.'
    )

    apiPost.mockClear()
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))

    expect(
      screen.queryByText(
        'El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.'
      )
    ).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })
})

// US-12 (D-8): toast informativo cuando la respuesta de reject trae
// baseline_absent:true — condición de carrera entre el baseline_status leído
// al abrir el modal y el estado real al confirmar.
describe('EventDetail — US-12 (toast baseline_absent en reject)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    toastError.mockReset()
    toastSuccess.mockReset()
    toastInfo.mockReset()
  })

  it('reject con baseline_absent:true en la respuesta muestra el toast informativo', async () => {
    mockDetailAndChain(makeEvent({ id: 60, status: 'pending' }))
    apiPost.mockResolvedValue({
      data: { event_id: 60, status: 'rejected', baseline_absent: true },
    })
    const user = userEvent.setup()

    renderDetail(60)

    await user.click(await screen.findByRole('button', { name: 'Rechazar' }))
    await user.click(await screen.findByRole('button', { name: 'Confirmar rechazo' }))

    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith(
        'El baseline ya no tiene archivo: el rechazo no ejecutó ninguna acción.'
      )
    )
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('reject sin baseline_absent muestra el toast de éxito actual', async () => {
    mockDetailAndChain(makeEvent({ id: 61, status: 'pending' }))
    apiPost.mockResolvedValue({
      data: { event_id: 61, status: 'rejected', baseline_absent: false },
    })
    const user = userEvent.setup()

    renderDetail(61)

    await user.click(await screen.findByRole('button', { name: 'Rechazar' }))
    await user.click(await screen.findByRole('button', { name: 'Confirmar rechazo' }))

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Evento rechazado'))
    expect(toastInfo).not.toHaveBeenCalled()
  })
})

describe('EventDetail — detección offline (D80/RN-174)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('con detected_offline=true muestra el indicador con su explicación', async () => {
    mockDetailAndChain(makeEvent({ id: 21, path: '/etc/hosts', detected_offline: true }))

    renderDetail(21)

    const badge = await screen.findByText('detectado offline')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('title', expect.stringMatching(/agente detenido/))
    expect(badge).toHaveAttribute('title', expect.stringMatching(/al arrancar/))
  })

  it.each([
    ['false', false],
    ['null', null],
    ['ausente', undefined],
  ])('con detected_offline %s no muestra el indicador y los demás siguen igual', async (_label, value) => {
    mockDetailAndChain(
      makeEvent({
        id: 22,
        path: '/etc/hosts',
        is_symlink: true,
        symlink_target: '/etc/other',
        action_failed: true,
        detected_offline: value,
      })
    )

    renderDetail(22)

    await screen.findByText('/etc/hosts')
    expect(screen.queryByText('detectado offline')).not.toBeInTheDocument()
    expect(screen.getByText('symlink')).toBeInTheDocument()
    expect(screen.getByText('Remediación fallida')).toBeInTheDocument()
  })
})

// D83/RN-177: liberación de cuarentena desde el detalle.
describe('EventDetail — liberar cuarentena (D83/RN-177)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    toastError.mockReset()
    toastSuccess.mockReset()
    toastInfo.mockReset()
  })

  const releaseButton = () => screen.queryByRole('button', { name: 'Liberar cuarentena' })

  it.each([
    ['quarantined', 'quarantined'],
    ['rejected', 'quarantined'],
  ] as const)('un evento %s con quarantine_state %s muestra el botón', async (status, state) => {
    mockDetailAndChain(makeEvent({ id: 60, status, quarantine_state: state }))
    renderDetail(60)
    await screen.findByText('/etc/passwd')
    expect(releaseButton()).toBeInTheDocument()
    expect(releaseButton()).toBeEnabled()
  })

  it.each(['none', 'released', 'discarded'] as const)(
    'con quarantine_state %s el botón no está',
    async (state) => {
      mockDetailAndChain(makeEvent({ id: 61, status: 'quarantined', quarantine_state: state }))
      renderDetail(61)
      await screen.findByText('/etc/passwd')
      expect(releaseButton()).not.toBeInTheDocument()
    },
  )

  it('sin quarantine_state (backend anterior) el botón no está', async () => {
    mockDetailAndChain(makeEvent({ id: 62, status: 'quarantined' }))
    renderDetail(62)
    await screen.findByText('/etc/passwd')
    expect(releaseButton()).not.toBeInTheDocument()
  })

  it('con un comando pendiente el botón está deshabilitado', async () => {
    mockDetailAndChain(
      makeEvent({ id: 63, status: 'quarantined', quarantine_state: 'quarantined', ack_status: 'pending' }),
    )
    renderDetail(63)
    await screen.findByText('/etc/passwd')
    expect(releaseButton()).toBeDisabled()
  })

  it('confirmar envía modo y motivo, cierra el modal y avisa que fue solicitada', async () => {
    mockDetailAndChain(makeEvent({ id: 64, status: 'quarantined', quarantine_state: 'quarantined' }))
    apiPost.mockResolvedValue({
      data: { event_id: 64, command_id: 'c', mode: 'discard', ack_status: 'pending' },
    })
    const user = userEvent.setup()

    const { queryClient } = renderDetail(64)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: 'Liberar cuarentena' }))
    await user.click(screen.getByLabelText(/Descartar el archivo cuarentenado/))
    await user.type(screen.getByLabelText(/Motivo/), 'falso positivo')
    await user.click(screen.getByRole('button', { name: 'Confirmar liberación' }))

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/events/64/quarantine/release', {
        mode: 'discard',
        reason: 'falso positivo',
      }),
    )
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Liberación de cuarentena solicitada'))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['event', 64] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['events'] })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('409 release_in_progress muestra su mensaje, refresca el evento y deja el modal abierto', async () => {
    mockDetailAndChain(makeEvent({ id: 65, status: 'quarantined', quarantine_state: 'quarantined' }))
    apiPost.mockRejectedValue(axiosErrorWithStatus(409, { detail: { code: 'release_in_progress' } }))
    const user = userEvent.setup()

    const { queryClient } = renderDetail(65)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: 'Liberar cuarentena' }))
    await user.click(screen.getByLabelText(/Restaurar la versión aprobada/))
    await user.type(screen.getByLabelText(/Motivo/), 'x')
    await user.click(screen.getByRole('button', { name: 'Confirmar liberación' }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        'Ya hay una liberación de cuarentena en curso para este evento.',
      ),
    )
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['event', 65] })
  })

  it('409 quarantine_not_releasable muestra su mensaje', async () => {
    mockDetailAndChain(makeEvent({ id: 66, status: 'quarantined', quarantine_state: 'quarantined' }))
    apiPost.mockRejectedValue(axiosErrorWithStatus(409, { detail: { code: 'quarantine_not_releasable' } }))
    const user = userEvent.setup()

    renderDetail(66)

    await user.click(await screen.findByRole('button', { name: 'Liberar cuarentena' }))
    await user.click(screen.getByLabelText(/Descartar/))
    await user.type(screen.getByLabelText(/Motivo/), 'x')
    await user.click(screen.getByRole('button', { name: 'Confirmar liberación' }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith('La cuarentena de este evento ya no se puede liberar.'),
    )
  })

  it('el modal reabierto empieza vacío', async () => {
    mockDetailAndChain(makeEvent({ id: 67, status: 'quarantined', quarantine_state: 'quarantined' }))
    const user = userEvent.setup()
    renderDetail(67)

    await user.click(await screen.findByRole('button', { name: 'Liberar cuarentena' }))
    await user.type(screen.getByLabelText(/Motivo/), 'borrador')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    await user.click(screen.getByRole('button', { name: 'Liberar cuarentena' }))

    expect(screen.getByLabelText(/Motivo/)).toHaveValue('')
  })
})
