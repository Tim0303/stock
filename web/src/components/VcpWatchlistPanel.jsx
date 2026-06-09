import React from 'react'

// 狀態 → 顏色：剛突破=綠、待突破(量縮)/待突破=琥珀
function StatusBadge({ status }) {
  const isBreakout = status === '剛突破'
  const style = isBreakout
    ? { bg: 'rgba(0,255,136,0.12)', border: 'rgba(0,255,136,0.45)', color: '#00ff88' }
    : { bg: 'rgba(255,184,0,0.12)', border: 'rgba(255,184,0,0.40)', color: '#ffb800' }
  return (
    <span
      className="px-2 py-0.5 rounded-sm text-xs"
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        color: style.color,
        fontFamily: 'Noto Sans TC',
        whiteSpace: 'nowrap',
      }}
    >
      {status || '—'}
    </span>
  )
}

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

function ScoreCell({ score }) {
  const n = Number(score)
  let color = '#4a6080'
  if (n >= 80) color = '#00ff88'
  else if (n >= 60) color = '#00d4ff'
  else if (n >= 40) color = '#ffb800'
  return (
    <span className="mono text-sm font-bold" style={{ color }}>
      {Number.isNaN(n) ? '—' : n.toFixed(1)}
    </span>
  )
}

export default function VcpWatchlistPanel({ data = [], scanDate, loading, error }) {
  return (
    <div className="panel rounded-sm" style={{ minHeight: '280px' }}>
      <div className="p-4">
        <div className="section-header text-sm mb-4">
          <span style={{ color: '#00ff88' }}>◆</span>
          VCP 突破監控
          <span className="mono text-xs" style={{ color: '#4a6080' }}>
            {loading ? 'LOADING...' : scanDate ? `${scanDate} · ${data.length} 檔` : `${data.length} 檔`}
          </span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {loading && !data.length ? (
          <div className="flex items-center justify-center py-12">
            <div className="mono text-sm" style={{ color: '#1f3060' }}>[ SCANNING VCP... ]</div>
          </div>
        ) : data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>
              今日無 VCP 候選（市場條件不符）
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid #1a2540' }}>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>代號</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>名稱</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>分數</th>
                  <th className="mono text-right pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>收縮</th>
                  <th className="mono text-right pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>末回檔%</th>
                  <th className="mono text-right pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>距樞紐%</th>
                  <th className="mono text-left pb-2 pl-3 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>狀態</th>
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr
                    key={row.symbol}
                    style={{ borderBottom: '1px solid #0d1426' }}
                  >
                    <td className="py-2.5 px-2">
                      <span className="mono text-sm font-bold" style={{ color: '#c8daf0' }}>{row.symbol}</span>
                    </td>
                    <td className="py-2.5 px-2">
                      <span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.85rem' }}>{row.name || '—'}</span>
                    </td>
                    <td className="py-2.5 px-2">
                      <ScoreCell score={row.score} />
                    </td>
                    <td className="py-2.5 px-2 text-right">
                      <span className="mono text-sm" style={{ color: '#8ba3c7' }}>{row.contraction_count ?? '—'}</span>
                    </td>
                    <td className="py-2.5 px-2 text-right">
                      <span className="mono text-sm" style={{ color: '#8ba3c7' }}>{fmtNum(row.last_drawdown_pct)}</span>
                    </td>
                    <td className="py-2.5 px-2 text-right">
                      <span className="mono text-sm" style={{ color: '#8ba3c7' }}>{fmtNum(row.distance_pct)}</span>
                    </td>
                    <td className="py-2.5 px-2 pl-3">
                      <StatusBadge status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
