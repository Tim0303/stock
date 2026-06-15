import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { getCookie } from '../api.js'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [state, setState] = useState({ loading: true, user: null })

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/auth/me', { credentials: 'include' })
      if (r.ok) setState({ loading: false, user: await r.json() })
      else setState({ loading: false, user: null })
    } catch {
      setState({ loading: false, user: null })
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const logout = useCallback(async () => {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST', credentials: 'include',
        headers: { 'X-CSRF-Token': getCookie('csrf_token') },
      })
    } finally {
      setState({ loading: false, user: null })
      window.location.assign('/login')
    }
  }, [])

  return <AuthCtx.Provider value={{ ...state, refresh, logout }}>{children}</AuthCtx.Provider>
}

export const useAuth = () => useContext(AuthCtx)
