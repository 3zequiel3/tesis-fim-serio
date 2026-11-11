import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'

vi.mock('@/hooks/useAlertsSSE', () => ({ useAlertsSSE: vi.fn() }))
vi.mock('@/api/client', () => {
  const get = (url: string) =>
    Promise.resolve({
      data:
        url === '/health/components'
          ? { postgres: 'ok', valkey: 'ok', n8n: 'ok', agents: { status: 'ok', items: [] }, checked_at: 't' }
          : { count: 0 },
    })
  return { apiClient: { get }, default: { get } }
})

import { MainLayout } from './MainLayout'
import { useAuthStore } from '@/stores/auth.store'

function mockWidth(px: number) {
  window.matchMedia = ((query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query)
    return {
      matches: min ? px >= Number(min[1]) : false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }
  }) as unknown as typeof window.matchMedia
}

function renderLayout() {
  return renderWithProviders(
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/dashboard" element={<h1>Contenido</h1>} />
      </Route>
    </Routes>,
    { route: '/dashboard' },
  )
}

function setRole(role: string) {
  useAuthStore.setState({ accessToken: 't', user: { id: 1, username: 'ana', role, must_change_password: false } })
}

describe('MainLayout — responsive navigation (D93/RN-187)', () => {
  beforeEach(() => setRole('admin'))
  afterEach(() => {
    useAuthStore.setState({ accessToken: null, user: null })
  })

  it('on desktop shows the grouped sidebar and no menu button', () => {
    mockWidth(1280)
    renderLayout()
    const nav = screen.getByRole('navigation', { name: 'Navegación principal' })
    expect(within(nav).getByText('Supervisión')).toBeInTheDocument()
    expect(within(nav).getByText('Configuración')).toBeInTheDocument()
    for (const label of ['Dashboard', 'Eventos', 'Alertas', 'Reglas', 'Agentes']) {
      expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: 'Abrir menú de navegación' })).toBeNull()
  })

  it('collapses to an icon rail that keeps accessible labels', async () => {
    mockWidth(1280)
    renderLayout()
    await userEvent.click(screen.getByRole('button', { name: 'Contraer menú lateral' }))
    const nav = screen.getByRole('navigation', { name: 'Navegación principal' })
    expect(within(nav).getByRole('link', { name: 'Eventos' })).toBeInTheDocument()
    expect(within(nav).queryByText('Supervisión')).toBeNull()
    expect(screen.getByRole('button', { name: 'Expandir menú lateral' })).toBeInTheDocument()
  })

  it('at 375 px the sidebar is gone and the menu button opens a panel that Escape closes', async () => {
    mockWidth(375)
    renderLayout()
    expect(screen.queryByRole('navigation', { name: 'Navegación principal' })).toBeNull()

    const button = screen.getByRole('button', { name: 'Abrir menú de navegación' })
    await userEvent.click(button)
    const panel = screen.getByRole('dialog')
    expect(within(panel).getByRole('link', { name: 'Eventos' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(button).toHaveFocus()
  })

  it('shows the read-only legend for a role that is not admin', () => {
    mockWidth(1280)
    setRole('viewer')
    renderLayout()
    expect(screen.getByText('Modo lectura: tu usuario no puede modificar la configuración.')).toBeInTheDocument()
  })

  it('does not show the read-only legend for an admin', () => {
    mockWidth(1280)
    renderLayout()
    expect(screen.queryByText(/Modo lectura/)).toBeNull()
  })
})
