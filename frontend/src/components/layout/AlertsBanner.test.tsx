import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AlertsBanner } from './AlertsBanner'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function mockFailedCount(count: number) {
  apiGet.mockImplementation((url: string) => {
    if (url !== '/alerts/failed/count') throw new Error(`URL no mockeada en el test: ${url}`)
    return Promise.resolve({ data: { count } })
  })
}

// US-29, US-05, D6/RN-102 (D-3, D-4): banner sin umbral de retry_count, texto
// literal del criterio, enlace a /alerts/failed y query key ['alerts','failed','count'].
describe('AlertsBanner — US-29/US-05: banner amarillo de la DLQ', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('no muestra ningun banner cuando count=0', async () => {
    mockFailedCount(0)

    renderWithProviders(<AlertsBanner />)

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('muestra un banner amarillo con el texto literal de US-29 cuando count=4', async () => {
    mockFailedCount(4)

    renderWithProviders(<AlertsBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Notificaciones pendientes: 4 alertas no pudieron ser enviadas')
    expect(banner.className).toMatch(/bg-yellow-/)
  })

  it('usa el singular cuando count=1', async () => {
    mockFailedCount(1)

    renderWithProviders(<AlertsBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Notificaciones pendientes: 1 alerta no pudo ser enviada')
  })

  it('una alerta con retry_count=0 (n8n sin configurar) igual cuenta — sin umbral', async () => {
    // El backend ya filtra sin umbral (D-3); el frontend sólo confía en count.
    mockFailedCount(1)

    renderWithProviders(<AlertsBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('1 alerta no pudo ser enviada')
  })

  it('el enlace apunta a /alerts/failed', async () => {
    mockFailedCount(2)

    renderWithProviders(<AlertsBanner />)

    await screen.findByRole('alert')
    const link = screen.getByRole('link', { name: /revisar/i })
    expect(link).toHaveAttribute('href', '/alerts/failed')
  })

  it('consulta GET /alerts/failed/count', async () => {
    mockFailedCount(1)

    renderWithProviders(<AlertsBanner />)
    await screen.findByRole('alert')

    expect(apiGet).toHaveBeenCalledWith('/alerts/failed/count')
  })

  it('el banner desaparece cuando un refetch devuelve count=0', async () => {
    mockFailedCount(3)
    const { queryClient } = renderWithProviders(<AlertsBanner />)

    await screen.findByRole('alert')

    mockFailedCount(0)
    await queryClient.refetchQueries({ queryKey: ['alerts', 'failed', 'count'] })

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })
})
