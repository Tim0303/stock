import React, { useState, useMemo } from 'react'

const SKILL_META = {
  'strat-vcp': { label: 'VCP 突破', accent: '#00ff88' },
  'strat-5-10-20': { label: '5-10-20 順勢', accent: '#00d4ff' },
  'strat-spring': { label: '破支撐拉回', accent: '#2dd4bf' },
  'strat-bb-trend': { label: '布林通道趨勢續抱', accent: '#818cf8' },
  'strat-bb-breakout': { label: '布林開口放量突破', accent: '#f59e0b' },
  'ml-logreg': { label: 'ML 預測', accent: '#ff6ec7' },
}
const ORDER = ['strat-vcp', 'strat-5-10-20', 'strat-spring', 'strat-bb-trend', 'strat-bb-breakout', 'ml-logreg']

// 可排序欄位定義（type 決定比較方式）
const COLS = [
  { key: 'symbol', label: '代號', type: 'str' },
  { key: 'name', label: '名稱', type: 'str' },
  { key: 'entry_date', label: '進場日', type: 'str' },
  { key: 'exit_date', label: '出場日', type: 'str' },
  { key: 'entry_price', label: '進場價', type: 'num' },
  { key: 'exit_price', label: '出場價', type: 'num' },
  { key: 'current_price', label: '現價', type: 'num' },
  { key: 'ret_pct', label: '報酬', type: 'num' },
  { key: 'status', label: '狀態', type: 'status' },
]
// 狀態排序權重：持有中 → 待進場 → 已平倉
const STATUS_RANK = { holding: 0, pending: 1, closed: 2 }

// 台股慣例：紅漲綠跌（正=紅、負=綠）
function retColor(v) {
  if (v === null || v === undefined) return '#4a6080'
  return Number(v) >= 0 ? '#ff5b6e' : '#2dd47e'
}
function fmt(v, d = 2) {
  return (v === null || v === undefined || v === '') ? '—' : Number(v).toFixed(d)
}

export default function AnalystPositionsPanel({ data = [], loading, error, onSelect, selectedSymbol }) {
  const [active, setActive] = useState(null)
  const [sort, setSort] = useState({ key: null, dir: 'asc' })
  const bySkill = {}
  for (const r of data) { (bySkill[r.skill] || (bySkill[r.skill] = [])).push(r) }
  const skills = ORDER.filter((s) => bySkill[s] && bySkill[s].length)
  const cur = (active && bySkill[active]) ? active : (skills[0] || null)
  const baseRows = cur ? bySkill[cur] : []
  const meta = SKILL_META[cur] || { label: cur, accent: '#8ba3c7' }

  // 點表頭排序：同欄循環 升序 → 降序 → 復原(原始順序)；換欄則從升序開始
  const clickHeader = (key) =>
    setSort((s) => {
      if (s.key !== key) return { key, dir: 'asc' }
      if (s.dir === 'asc') return { key, dir: 'desc' }
      return { key: null, dir: 'asc' }   // 第三次點擊：清除排序，回到原始順序
    })

  const rows = useMemo(() => {
    if (!sort.key) return baseRows
    const col = COLS.find((c) => c.key === sort.key)
    const sign = sort.dir === 'asc' ? 1 : -1
    return [...baseRows].sort((a, b) => {
      let av = a[sort.key], bv = b[sort.key]
      if (col.type === 'status') { av = STATUS_RANK[av] ?? 9; bv = STATUS_RANK[bv] ?? 9 }
      else if (col.type === 'num') {
        av = (av === null || av === undefined || av === '') ? null : Number(av)
        bv = (bv === null || bv === undefined || bv === '') ? null : Number(bv)
        // 空值一律排在最後（不受升降序影響）
        if (av === null && bv === null) return 0
        if (av === null) return 1
        if (bv === null) return -1
      } else { av = av || ''; bv = bv || '' }
      if (av < bv) return -1 * sign
      if (av > bv) return 1 * sign
      return 0
    })
  }, [baseRows, sort])
  const holdN = rows.filter((r) => r.status === 'holding').length
  const pendN = rows.filter((r) => r.status === 'pending').length
  const closeN = rows.length - holdN - pendN

  const th = { color: '#4a6080', fontWeight: 400, whiteSpace: 'nowrap' }

  return (
    <div className="panel rounded-sm" style={{ minHeight: '280px' }}>
      <div className="p-4">
        <div className="section-header text-sm mb-3 flex items-center gap-2">
          <span style={{ color: '#00d4ff' }}>◆</span>
          分析師持股追蹤
          <span className="mono text-xs" style={{ color: '#4a6080' }}>
            {loading && !data.length ? 'LOADING...' : `${data.length} 筆訊號`}
          </span>
          <span className="mono text-xs ml-auto" style={{ color: '#2a3a5a' }}>live 訊號模擬持股 · 持有中=未實現／已平倉=實現</span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {skills.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>尚無 live 持股訊號（每日收盤後累積）</div>
          </div>
        ) : (
          <>
            <div className="flex gap-1.5 mb-3 flex-wrap">
              {skills.map((s) => {
                const m = SKILL_META[s] || { label: s, accent: '#8ba3c7' }
                const isA = s === cur
                return (
                  <button
                    key={s}
                    onClick={() => setActive(s)}
                    className="mono text-xs px-2.5 py-1 rounded-sm"
                    style={{
                      border: `1px solid ${isA ? m.accent : '#1a2540'}`,
                      color: isA ? m.accent : '#8ba3c7',
                      background: isA ? `${m.accent}14` : 'transparent',
                      whiteSpace: 'nowrap', fontFamily: 'Noto Sans TC', fontWeight: isA ? 700 : 400,
                    }}
                  >
                    {m.label} ({bySkill[s].length})
                  </button>
                )
              })}
            </div>

            <div className="mono text-xs mb-2" style={{ color: '#4a6080' }}>
              持有中 <span style={{ color: meta.accent }}>{holdN}</span>
              {' · '}待進場 <span style={{ color: '#ffb800' }}>{pendN}</span>
              {' · '}已平倉 <span style={{ color: '#8ba3c7' }}>{closeN}</span>
              <span className="ml-2" style={{ color: '#2a3a5a' }}>· 進場＝訊號日隔日開盤（與報告一致）</span>
            </div>

            <div className="overflow-auto" style={{ maxHeight: '480px' }}>
              <table className="w-full text-sm">
                <thead style={{ position: 'sticky', top: 0, background: '#0a1020', zIndex: 1 }}>
                  <tr style={{ borderBottom: '1px solid #1a2540' }}>
                    {COLS.map((c) => {
                      const isS = sort.key === c.key
                      return (
                        <th
                          key={c.key}
                          className="mono text-center pb-2 text-xs select-none"
                          style={{ ...th, cursor: 'pointer', color: isS ? meta.accent : '#4a6080' }}
                          onClick={() => clickHeader(c.key)}
                          title="點擊排序"
                        >
                          {c.label}
                          <span className="ml-1" style={{ color: isS ? meta.accent : '#2a3a5a' }}>
                            {isS ? (sort.dir === 'asc' ? '▲' : '▼') : '⇅'}
                          </span>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const sel = r.symbol === selectedSymbol
                    return (
                      <tr
                        key={`${r.symbol}-${r.entry_date}-${i}`}
                        className="candidate-row"
                        style={{ borderBottom: '1px solid #0d1426', cursor: 'pointer', background: sel ? `${meta.accent}10` : undefined }}
                        onClick={() => onSelect && onSelect(r.symbol)}
                      >
                        <td className="py-2 px-2 text-center"><span className="mono text-sm font-bold" style={{ color: sel ? meta.accent : '#c8daf0' }}>{r.symbol}</span></td>
                        <td className="py-2 px-2 text-center"><span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.82rem' }}>{r.name || '—'}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-xs" style={{ color: '#8ba3c7' }}>{r.entry_date || '—'}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-xs" style={{ color: r.exit_date ? '#8ba3c7' : '#2a3a5a' }}>{r.exit_date || '—'}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-xs" style={{ color: '#8ba3c7' }}>{fmt(r.entry_price)}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-xs" style={{ color: r.exit_price ? '#8ba3c7' : '#2a3a5a' }}>{fmt(r.exit_price)}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-xs" style={{ color: '#c8daf0' }}>{fmt(r.current_price)}</span></td>
                        <td className="py-2 px-2 text-center"><span className="mono text-sm font-bold" style={{ color: retColor(r.ret_pct) }}>{r.ret_pct == null ? '—' : `${Number(r.ret_pct) >= 0 ? '+' : ''}${r.ret_pct}%`}</span></td>
                        <td className="py-2 px-2 text-center">
                          {(() => {
                            const st = r.status === 'holding'
                              ? { t: '持有中', c: meta.accent, b: `${meta.accent}18`, bd: `${meta.accent}66` }
                              : r.status === 'pending'
                                ? { t: '待進場', c: '#ffb800', b: 'rgba(255,184,0,0.12)', bd: 'rgba(255,184,0,0.45)' }
                                : { t: '已平倉', c: '#8ba3c7', b: 'rgba(74,96,128,0.15)', bd: '#2a3a5a' }
                            return (
                              <span className="mono text-xs px-1.5 py-0.5 rounded-sm" style={{
                                background: st.b, border: `1px solid ${st.bd}`, color: st.c,
                                fontFamily: 'Noto Sans TC', whiteSpace: 'nowrap',
                              }}>{st.t}</span>
                            )
                          })()}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
