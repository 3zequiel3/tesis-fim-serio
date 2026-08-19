import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Sin `globals: true` Testing Library no puede registrar su cleanup automatico,
// asi que se desmonta explicitamente despues de cada test.
afterEach(() => {
  cleanup()
})
