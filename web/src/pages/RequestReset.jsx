import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiJson } from '../api.js'
import { AuthShell, Field, SubmitBtn, Msg } from './authui.jsx'

export default function RequestReset() {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault(); setBusy(true)
    try { await apiJson('/api/auth/request-reset', { method: 'POST', body: JSON.stringify({ email }) }) }
    finally { setDone(true); setBusy(false) }
  }

  return (
    <AuthShell title="忘記密碼" footer={<Link to="/login" style={{ color: '#00d4ff' }}>回登入</Link>}>
      {done ? (
        <Msg kind="ok">若該帳號存在，我們已寄出重設連結（1 小時內有效）。開發模式請見 docker logs stock-api。</Msg>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
          <SubmitBtn disabled={busy}>{busy ? '送出中…' : '寄送重設連結'}</SubmitBtn>
        </form>
      )}
    </AuthShell>
  )
}
