import { Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './auth/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import { DashboardRedirect } from './pages/Dashboards'
import { FullPageMessage } from './components/ui'

/**
 * Application routes.
 *
 * /login and /register are public. Everything else sits behind
 * <ProtectedRoute>, which redirects logged-out visitors to /login and blocks
 * wrong-role access with a 403 page.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardRedirect />} />
      </Route>

      <Route
        path="*"
        element={
          <FullPageMessage
            title="404 — Page not found"
            body="That page does not exist."
            linkTo="/dashboard"
            linkLabel="Back to dashboard"
          />
        }
      />
    </Routes>
  )
}
