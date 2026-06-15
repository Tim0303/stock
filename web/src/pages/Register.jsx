import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiJson } from '../api.js'
import { AuthShell, Field, SubmitBtn, Msg } from './authui.jsx'
import Disclaimer from '../components/Disclaimer.jsx'

export default function Register() {
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault(); setErr('')
    if (pw.length < 8) { setErr('密碼至少 8 碼'); return }
    setBusy(true)
    try {
      await apiJson('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password: pw }) })
      setDone(true)
    } catch (ex) { setErr(ex.message || '註冊失敗') } finally { setBusy(false) }
  }

  if (done) {
    return (
      <AuthShell title="驗證信已寄出" footer={<Link to="/login" style={{ color: '#00d4ff' }}>前往登入</Link>}>
        <Msg kind="ok">若 Email 有效，我們已寄出驗證連結，請點擊完成驗證並啟用 14 天免費試用。</Msg>
        <div className="mono" style={{ fontSize: '0.7rem', color: '#4a6080', lineHeight: 1.7 }}>
          （開發模式：驗證連結會印在 <b>docker logs stock-api</b>）
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="免費註冊（14 天試用）" footer={<>已有帳號？<Link to="/login" style={{ color: '#00d4ff' }}>登入</Link></>}>
      <form onSubmit={submit}>
        <Msg>{err}</Msg>
        <Field label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
        <Field label="密碼（至少 8 碼）" type="password" value={pw} onChange={e => setPw(e.target.value)} required autoComplete="new-password" />
        <SubmitBtn disabled={busy}>{busy ? '送出中…' : '註冊並開始試用'}</SubmitBtn>
      </form>
      <div style={{ marginTop: 16 }}><Disclaimer compact /></div>
    </AuthShell>
  )
}
