import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'

export function Navbar() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-700">
      <div className="text-sm text-gray-500">
        {/* Breadcrumb / título de página se agrega en C18 */}
      </div>
      <div className="flex items-center gap-4">
        {user && (
          <span className="text-sm text-gray-300 font-medium">{user.username}</span>
        )}
        <button
          onClick={handleLogout}
          className="text-sm px-3 py-1.5 rounded-md border border-gray-600 text-gray-300 hover:bg-gray-800 transition-colors"
          type="button"
        >
          Cerrar sesión
        </button>
      </div>
    </header>
  )
}
