// 統一 API 呼叫：永遠帶 cookie、unsafe method 帶 CSRF、401→/login、402/403→/account。
export function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)')
  return m ? m.pop() : ''
}

let redirecting = false
function redirect(to) {
  if (redirecting) return
  redirecting = true
  window.location.assign(to)
}

export async function apiFetch(path, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase()
  const headers = { ...(opts.headers || {}) }
  if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) headers['X-CSRF-Token'] = getCookie('csrf_token')
  const res = await fetch(path, { ...opts, method, headers, credentials: 'include' })
  const isAuthPath = path.includes('/api/auth/')
  if (res.status === 401 && !isAuthPath) { redirect('/login'); throw new Error('unauthenticated') }
  if ((res.status === 402 || res.status === 403) && !isAuthPath) { redirect('/account'); throw new Error('subscription') }
  return res
}

// 回傳 JSON；非 2xx 丟出含 detail 的錯誤（auth 表單用）
export async function apiJson(path, opts) {
  const res = await apiFetch(path, opts)
  let data = null
  try { data = await res.json() } catch { /* ignore */ }
  if (!res.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`)
  return data
}
