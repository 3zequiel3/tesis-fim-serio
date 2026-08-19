import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { AlertsBanner } from './AlertsBanner'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function mockFailedAlerts(total: number) {
  apiGet.mockImplementation((url: string) => {
    if (url !== '/alerts') throw new Error(`URL no mockeada en el test: ${url}`)
    return Promise.resolve({ data: { items: [], total, page: 1, size: 1 } })
  })
}

// US-05, criterio del banner amarillo (detalle en US-29).
describe('AlertsBanner — US-05: banner amarillo de notificaciones fallidas', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('no muestra ningun banner cuando no hay alertas fallidas', async () => {
    mockFailedAlerts(0)

    renderWithProviders(<AlertsBanner />)

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('muestra un banner amarillo con la cantidad de alertas fallidas en la DLQ', async () => {
    mockFailedAlerts(4)

    renderWithProviders(<AlertsBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/4 alertas fallidas en la DLQ/i)
    expect(banner.className).toMatch(/bg-yellow-/)
  })

  it('ofrece un enlace para revisar las alertas fallidas', async () => {
    mockFailedAlerts(2)

    renderWithProviders(<AlertsBanner />)

    await screen.findByRole('alert')
    const link = screen.getByRole('link', { name: /revisar/i })
    expect(link).toHaveAttribute('href', '/alerts')
  })

  it('consulta unicamente las alertas en estado failed', async () => {
    mockFailedAlerts(1)

    renderWithProviders(<AlertsBanner />)
    await screen.findByRole('alert')

    expect(apiGet).toHaveBeenCalledWith('/alerts', { params: { status: 'failed', size: 1 } })
  })

  it('usa el singular cuando hay una sola alerta fallida', async () => {
    mockFailedAlerts(1)

    renderWithProviders(<AlertsBanner />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/1 alerta fallida en la DLQ/i)
  })
})
