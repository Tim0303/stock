import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'

function daysLeft(iso) {
  if (!iso) return null
  return Math.ceil((new Date(iso) - new Date()) / 86400000)
}

// 試用倒數橫幅（儀表板頂部）；非試用狀態不顯示。
export default function TrialBanner() {
  const { user } = useAuth()
  const sub = user && user.subscription
  if (!sub || sub.status !== 'trialing') return null
  const d = daysLeft(sub.trial_end)
  if (d == null) return null
  const urgent = d <= 3

  return (
    <div className="mono" style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
      fontSize: '0.78rem', padding: '7px 12px', marginBottom: 12, borderRadius: 5,
      color: urgent ? '#ffb800' : '#8ba3c7',
      background: urgent ? 'rgba(255,184,0,0.08)' : 'rgba(0,212,255,0.05)',
      border: `1px solid ${urgent ? 'rgba(255,184,0,0.35)' : 'rgba(0,212,255,0.2)'}`,
    }}>
      免費試用剩餘 <b style={{ color: urgent ? '#ffb800' : '#00d4ff' }}>{d}</b> 天
      <Link to="/account" style={{ color: '#00d4ff', textDecoration: 'none' }}>· 帳戶/升級 →</Link>
    </div>
  )
}
