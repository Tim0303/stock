import React from 'react'
import { Link } from 'react-router-dom'

// 認證頁共用版型/元件（深色、與儀表板一致）
export function AuthShell({ title, children, footer }) {
  return (
    <div className="bg-grid" style={{ minHeight: '100vh', background: '#030712', display: 'flex',
      alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <div className="panel rounded-sm" style={{ width: '100%', maxWidth: 400, padding: '28px 26px' }}>
        <Link to="/" className="mono" style={{ color: '#00d4ff', fontSize: '0.8rem', textDecoration: 'none' }}>◆ AI 選股平台</Link>
        <h1 style={{ fontFamily: 'Noto Sans TC', color: '#e8f1ff', fontSize: '1.3rem', margin: '14px 0 18px' }}>{title}</h1>
        {children}
        {footer && <div className="mono" style={{ marginTop: 18, fontSize: '0.75rem', color: '#4a6080' }}>{footer}</div>}
      </div>
    </div>
  )
}

export function Field({ label, ...props }) {
  return (
    <label style={{ display: 'block', marginBottom: 14 }}>
      <span style={{ display: 'block', fontFamily: 'Noto Sans TC', fontSize: '0.8rem', color: '#8ba3c7', marginBottom: 5 }}>{label}</span>
      <input {...props} style={{
        width: '100%', padding: '9px 11px', background: '#0a1020', border: '1px solid #1f3060',
        borderRadius: 5, color: '#c8daf0', fontFamily: 'Share Tech Mono, monospace', fontSize: '0.9rem', outline: 'none',
      }} />
    </label>
  )
}

export function SubmitBtn({ children, disabled }) {
  return (
    <button type="submit" disabled={disabled} style={{
      width: '100%', padding: '10px', marginTop: 4, cursor: disabled ? 'not-allowed' : 'pointer',
      background: disabled ? '#0d1f33' : 'rgba(0,212,255,0.14)', border: '1px solid #00d4ff',
      color: disabled ? '#4a6080' : '#00d4ff', borderRadius: 5, fontFamily: 'Noto Sans TC', fontWeight: 700, fontSize: '0.9rem',
    }}>{children}</button>
  )
}

export function Msg({ kind = 'err', children }) {
  if (!children) return null
  const c = kind === 'ok' ? { bg: 'rgba(0,255,136,0.08)', bd: 'rgba(0,255,136,0.3)', fg: '#00ff88' }
    : { bg: 'rgba(255,51,102,0.08)', bd: 'rgba(255,51,102,0.3)', fg: '#ff5b6e' }
  return (
    <div className="mono" style={{ fontSize: '0.78rem', lineHeight: 1.6, color: c.fg, background: c.bg,
      border: `1px solid ${c.bd}`, borderRadius: 5, padding: '9px 11px', marginBottom: 14 }}>{children}</div>
  )
}
