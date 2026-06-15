import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import Disclaimer from '../components/Disclaimer.jsx'

export default function Landing() {
  const { user } = useAuth()
  const signedIn = user && user.authenticated

  return (
    <div className="bg-grid" style={{ minHeight: '100vh', background: '#030712', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 640, textAlign: 'center' }}>
          <div className="mono glow-cyan" style={{ color: '#00d4ff', fontSize: '0.8rem', letterSpacing: '0.2em', marginBottom: 14 }}>◆ AI STOCK INTELLIGENCE</div>
          <h1 style={{ fontFamily: 'Noto Sans TC', color: '#e8f1ff', fontSize: '2.1rem', lineHeight: 1.3, margin: '0 0 16px' }}>
            6 位 AI 分析師<br />同台比較的選股<span style={{ color: '#00d4ff' }}>資訊平台</span>
          </h1>
          <p style={{ fontFamily: 'Noto Sans TC', color: '#8ba3c7', fontSize: '1rem', lineHeight: 1.8, margin: '0 0 28px' }}>
            技術分析訊號、籌碼面、布林突破成功率模型、walk-forward 回測——
            每個策略的勝率/報酬/回撤透明呈現，<b style={{ color: '#c8daf0' }}>讓你自行評估</b>。
          </p>

          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 30 }}>
            {signedIn ? (
              <Link to={user.access ? '/app' : '/account'} className="mono" style={btn(true)}>
                {user.access ? '進入儀表板 →' : '前往帳戶 →'}
              </Link>
            ) : (
              <>
                <Link to="/register" className="mono" style={btn(true)}>免費試用 14 天</Link>
                <Link to="/login" className="mono" style={btn(false)}>登入</Link>
              </>
            )}
          </div>

          <div style={{ maxWidth: 560, margin: '0 auto' }}><Disclaimer /></div>
        </div>
      </div>
    </div>
  )
}

function btn(primary) {
  return {
    padding: '11px 26px', borderRadius: 5, textDecoration: 'none', fontWeight: 700, fontSize: '0.95rem',
    fontFamily: 'Noto Sans TC',
    background: primary ? 'rgba(0,212,255,0.14)' : 'transparent',
    border: `1px solid ${primary ? '#00d4ff' : '#1f3060'}`,
    color: primary ? '#00d4ff' : '#8ba3c7',
  }
}
