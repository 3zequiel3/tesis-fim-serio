import { useAuthStore } from '@/stores/auth.store'

/** Puts an authenticated user in the store (the console gates mutation controls by role, D93/RN-187). */
export function signInAs(role: string = 'admin') {
  useAuthStore.setState({
    accessToken: 'test-access-token',
    user: { id: 1, username: 'tester', role, must_change_password: false },
  })
}

export function signOut() {
  useAuthStore.setState({ accessToken: null, user: null })
}
