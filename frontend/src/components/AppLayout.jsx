import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/context'

/** Shell for every authenticated page: header, role-aware nav, logout. */
export default function AppLayout() {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <header className="app-bar">
        <Link to="/dashboard" className="brand">
          Auspify&nbsp;<span>TMS</span>
        </Link>

        <nav className="app-nav">
          <NavLink to="/dashboard" end>
            Dashboard
          </NavLink>
          {(user.role === 'teacher' || user.role === 'admin') && <NavLink to="/teacher">Exams</NavLink>}
          {user.role === 'student' && <NavLink to="/student">My exams</NavLink>}
          {user.role === 'student' && <NavLink to="/student/progress">My progress</NavLink>}
        </nav>

        <div className="app-user">
          <span className="user-name">{user.full_name}</span>
          <span className="badge neutral">{user.role}</span>
          <button type="button" className="btn secondary small-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      <main className="page">
        <Outlet />
      </main>
    </div>
  )
}
