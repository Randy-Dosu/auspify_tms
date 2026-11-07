import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './context'
import { FullPageMessage } from '../components/ui'

/**
 * Route guard.
 *
 * - while the session is being restored, show a loader (never a login flash)
 * - logged out -> redirect to /login, remembering where the user was going
 * - logged in but wrong role -> 403 page (not a redirect loop)
 */
export default function ProtectedRoute({ roles, children }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <FullPageMessage title="Checking your session…" />

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (roles && !roles.includes(user.role)) {
    return (
      <FullPageMessage
        title="403 — Not allowed"
        tone="error"
        body={`Your role (${user.role}) cannot open this page.`}
        linkTo="/dashboard"
        linkLabel="Go to my dashboard"
      />
    )
  }

  return children
}
