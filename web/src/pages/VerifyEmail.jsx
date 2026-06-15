import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiJson } from '../api.js'
import { AuthShell, Msg } from './authui.jsx'

export default function VerifyEmail() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState('pending') // pending | ok | fail

  useEffect(() => {
    const token = params.get('token')
    if (!token) { setStatus('fail'); return }
    apiJson('/api/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) })
      .then(() => setStatus('ok'))
      .catch(() => setStatus('fail'))
  }, [params])

  return (
    <AuthShell title="Email 驗證" footer={<Link to="/login" style={{ color: '#00d4ff' }}>前往登入</Link>}>
      {status === 'pending' && <div className="mono" style={{ color: '#8ba3c7', fontSize: '0.85rem' }}>驗證中…</div>}
      {status === 'ok' && <Msg kind="ok">驗證成功！您的 14 天免費試用已啟用，請登入開始使用。</Msg>}
      {status === 'fail' && <Msg>連結無效或已過期。請重新註冊或聯絡客服。</Msg>}
    </AuthShell>
  )
}
