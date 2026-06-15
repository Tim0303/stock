import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiJson } from '../api.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { AuthShell, Field, SubmitBtn, Msg } from './authui.jsx'

export default function Login() {
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const { refresh } = useAuth()

  async function submit(e) {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      await apiJson('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password: pw }) })
      await refresh()
      nav('/app')
    } catch (ex) { setErr(ex.message || '登入失敗') } finally { setBusy(false) }
  }

  return (
    <AuthShell title="登入" footer={<>還沒有帳號？<Link to="/register" style={{ color: '#00d4ff' }}>免費註冊</Link>　·　<Link to="/forgot" style={{ color: '#00d4ff' }}>忘記密碼</Link></>}>
      <form onSubmit={submit}>
        <Msg>{err}</Msg>
        <Field label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
        <Field label="密碼" type="password" value={pw} onChange={e => setPw(e.target.value)} required autoComplete="current-password" />
        <SubmitBtn disabled={busy}>{busy ? '登入中…' : '登入'}</SubmitBtn>
      </form>
    </AuthShell>
  )
}
