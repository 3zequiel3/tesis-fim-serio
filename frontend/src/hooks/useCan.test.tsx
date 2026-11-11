import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth.store'
import { Can } from '@/components/ui/Can'
import { useCan } from './useCan'

function setRole(role: string | null) {
  useAuthStore.setState({
    user: role ? { id: 1, username: 'u', role, must_change_password: false } : null,
  })
}

function Probe() {
  return <span>{useCan() ? 'puede' : 'no puede'}</span>
}

describe('useCan / Can', () => {
  afterEach(() => setRole(null))

  it('lets an admin mutate', () => {
    setRole('admin')
    render(
      <>
        <Probe />
        <Can>
          <button>Aprobar</button>
        </Can>
      </>,
    )
    expect(screen.getByText('puede')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Aprobar' })).toBeInTheDocument()
  })

  it('hides mutation controls for a viewer', () => {
    setRole('viewer')
    render(
      <>
        <Probe />
        <Can>
          <button>Aprobar</button>
        </Can>
      </>,
    )
    expect(screen.getByText('no puede')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aprobar' })).toBeNull()
  })

  it('hides them while nobody is authenticated', () => {
    setRole(null)
    render(<Probe />)
    expect(screen.getByText('no puede')).toBeInTheDocument()
  })
})
