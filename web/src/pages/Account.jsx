import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import Disclaimer from '../components/Disclaimer.jsx'

const STATUS_LABEL = {
  trialing: { t: '免費試用中', c: '#00d4ff' },
  active: { t: '訂閱中', c: '#00ff88' },
  past_due: { t: '付款逾期', c: '#ffb800' },
  canceled: { t: '已取消', c: '#8ba3c7' },
  expired: { t: '已到期', c: '#ff5b6e' },
}

function daysLeft(iso) {
  if (!iso) return null
  return Math.ceil((new Date(iso) - new Date()) / 86400000)
}

export default function Account() {
  const { user, logout, loading } = useAuth()
  if (loading) return null
  if (!user || !user.authenticated) return <div style={{ padding: 40, color: '#8ba3c7' }}>請先 <Link to="/login" style={{ color: '#00d4ff' }}>登入</Link></div>

  const sub = user.subscription
  const sl = sub ? (STATUS_LABEL[sub.status] || { t: sub.status, c: '#8ba3c7' }) : null
  const dleft = sub && sub.status === 'trialing' ? daysLeft(sub.trial_end) : null
  const active = user.access

  return (
    <div className="bg-grid" style={{ minHeight: '100vh', background: '#030712', padding: '32px 20px' }}>
      <div style={{ maxWidth: 560, margin: '0 auto' }}>
        <div className="section-header text-sm" style={{ marginBottom: 18 }}>
          <span style={{ color: '#00d4ff' }}>◆</span> 我的帳戶
        </div>

        <div className="panel rounded-sm" style={{ padding: 22, marginBottom: 16 }}>
          <Row k="Email" v={user.email} />
          <Row k="Email 驗證" v={user.email_verified
            ? <span style={{ color: '#00ff88' }}>已驗證</span>
            : <span style={{ color: '#ffb800' }}>未驗證（請查收驗證信）</span>} />
          <Row k="訂閱狀態" v={sl ? <span style={{ color: sl.c, fontWeight: 700 }}>{sl.t}</span> : '—'} />
          {dleft != null && <Row k="試用剩餘" v={<span style={{ color: dleft <= 3 ? '#ffb800' : '#c8daf0' }}>{dleft} 天</span>} />}
        </div>

        {active ? (
          <Link to="/app" className="mono" style={{ display: 'block', textAlign: 'center', padding: '11px',
            background: 'rgba(0,255,136,0.12)', border: '1px solid #00ff88', color: '#00ff88',
            borderRadius: 5, textDecoration: 'none', fontWeight: 700, marginBottom: 16 }}>
            進入戰情儀表板 →
          </Link>
        ) : (
          <div className="panel rounded-sm" style={{ padding: 18, marginBottom: 16, borderColor: '#3a2a10' }}>
            <div style={{ fontFamily: 'Noto Sans TC', color: '#ffb800', fontWeight: 700, marginBottom: 6 }}>
              {user.email_verified ? '試用已結束 / 訂閱未生效' : '請先完成 Email 驗證'}
            </div>
            <div className="mono" style={{ fontSize: '0.78rem', color: '#8ba3c7', lineHeight: 1.7 }}>
              {user.email_verified
                ? '付費訂閱即將推出（信用卡定期定額 / LINE Pay）。'
                : '驗證連結已寄至您的信箱（開發模式：見 docker logs stock-api）。'}
            </div>
            <button disabled className="mono" style={{ marginTop: 12, width: '100%', padding: '9px',
              background: '#0d1f33', border: '1px solid #1f3060', color: '#4a6080', borderRadius: 5, cursor: 'not-allowed' }}>
              升級付費（即將推出）
            </button>
          </div>
        )}

        <div style={{ marginBottom: 16 }}><Disclaimer /></div>

        <button onClick={logout} className="mono" style={{ width: '100%', padding: '9px',
          background: 'transparent', border: '1px solid #1f3060', color: '#8ba3c7', borderRadius: 5, cursor: 'pointer' }}>
          登出
        </button>
      </div>
    </div>
  )
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #0d1426' }}>
      <span className="mono" style={{ color: '#4a6080', fontSize: '0.8rem' }}>{k}</span>
      <span className="mono" style={{ color: '#c8daf0', fontSize: '0.85rem' }}>{v}</span>
    </div>
  )
}
