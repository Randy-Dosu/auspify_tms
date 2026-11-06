import { createContext, useContext } from 'react'

/** Auth context object (kept in its own module for Fast Refresh friendliness). */
export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
