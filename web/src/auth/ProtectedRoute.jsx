import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'

// 受保護路由：未登入→/login；已登入但無有效訂閱/未驗證→/account；其餘放行。
export default function ProtectedRoute({ children }) {
  const { loading, user } = useAuth()
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#030712' }}>
        <span className="mono" style={{ color: '#1f3060' }}>[ 載入中… ]</span>
      </div>
    )
  }
  if (!user || !user.authenticated) return <Navigate to="/login" replace />
  if (!user.access) return <Navigate to="/account" replace />
  return children
}
