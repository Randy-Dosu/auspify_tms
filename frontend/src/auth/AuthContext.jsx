import { useCallback, useEffect, useMemo, useState } from 'react'
import { AuthContext } from './context'
import { authApi, tokenStore } from '../api/client'

/**
 * Authentication state for the whole app.
 *
 * The token lives in localStorage (short-lived, header-only); the user object
 * is always re-fetched from /api/auth/me on load, so a revoked or expired
 * token cannot leave the UI stuck in a "logged in" state.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  // If no token is stored there is nothing to restore, so start settled.
  const [loading, setLoading] = useState(() => Boolean(tokenStore.get()))

  // Rehydrate the session on first load (the token can expire while stored).
  useEffect(() => {
    let cancelled = false
    if (!tokenStore.get()) return undefined
    ;(async () => {
      try {
        const data = await authApi.me()
        if (!cancelled) setUser(data.user)
      } catch {
        tokenStore.clear() // expired / revoked / tampered
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await authApi.login(email, password)
    tokenStore.set(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout() // revokes the token server-side
    } catch {
      /* already invalid - still clear locally */
    } finally {
      tokenStore.clear()
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, logout, isAuthenticated: Boolean(user) }),
    [user, loading, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

