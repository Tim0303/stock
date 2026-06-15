import React, { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiJson } from '../api.js'
import { AuthShell, Field, SubmitBtn, Msg } from './authui.jsx'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault(); setErr('')
    if (pw.length < 8) { setErr('密碼至少 8 碼'); return }
    setBusy(true)
    try {
      await apiJson('/api/auth/reset', { method: 'POST', body: JSON.stringify({ token: params.get('token') || '', password: pw }) })
      setDone(true)
    } catch (ex) { setErr(ex.message || '重設失敗') } finally { setBusy(false) }
  }

  return (
    <AuthShell title="重設密碼" footer={<Link to="/login" style={{ color: '#00d4ff' }}>前往登入</Link>}>
      {done ? (
        <Msg kind="ok">密碼已更新，請用新密碼登入。</Msg>
      ) : (
        <form onSubmit={submit}>
          <Msg>{err}</Msg>
          <Field label="新密碼（至少 8 碼）" type="password" value={pw} onChange={e => setPw(e.target.value)} required autoComplete="new-password" />
          <SubmitBtn disabled={busy}>{busy ? '更新中…' : '更新密碼'}</SubmitBtn>
        </form>
      )}
    </AuthShell>
  )
}
