import React from 'react'

function RatingBadge({ rating }) {
  const map = {
    buy: 'badge-buy',
    watch: 'badge-watch',
    skip: 'badge-skip',
    avoid: 'badge-avoid',
  }
  const labels = {
    buy: 'BUY',
    watch: 'WATCH',
    skip: 'SKIP',
    avoid: 'AVOID',
  }
  const cls = map[rating] || 'badge-skip'
  return <span className={`${cls} rounded-sm`}>{labels[rating] || rating?.toUpperCase() || '—'}</span>
}

function ScoreBar({ score }) {
  const pct = Math.max(0, Math.min(100, score || 0))
  let color = '#4a6080'
  if (pct >= 80) color = '#00ff88'
  else if (pct >= 60) color = '#00d4ff'
  else if (pct >= 40) color = '#ffb800'

  return (
    <div className="flex items-center gap-2">
      <span className="mono text-sm font-bold" style={{ color, minWidth: '28px' }}>{pct}</span>
      <div className="score-bar-bg flex-1" style={{ minWidth: '48px' }}>
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} />
      </div>
    </div>
  )
}

function SignalBadge({ signalType }) {
  if (!signalType) return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>
  const colors = {
    A: { bg: 'rgba(0,212,255,0.15)', border: 'rgba(0,212,255,0.5)', color: '#00d4ff' },
    B: { bg: 'rgba(123,94,167,0.15)', border: 'rgba(123,94,167,0.5)', color: '#b38fd4' },
    C: { bg: 'rgba(255,215,0,0.12)', border: 'rgba(255,215,0,0.4)', color: '#ffd700' },
  }
  const style = colors[signalType] || colors.A
  return (
    <span className="mono text-xs px-2 py-0.5 rounded-sm" style={{ background: style.bg, border: `1px solid ${style.border}`, color: style.color }}>
      訊號{signalType}
    </span>
  )
}

export default function CandidatesPanel({ data, loading, error, selectedSymbol, onSelect }) {
  return (
    <div className="panel rounded-sm" style={{ minHeight: '280px' }}>
      <div className="p-4">
        <div className="section-header text-sm mb-4">
          <span style={{ color: '#00d4ff' }}>◆</span>
          今日候選榜
          <span className="mono text-xs" style={{ color: '#4a6080' }}>
            {loading ? 'LOADING...' : `${data.length} 檔`}
          </span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {loading && !data.length ? (
          <div className="flex items-center justify-center py-12">
            <div className="mono text-sm" style={{ color: '#1f3060' }}>[ SCANNING MARKET... ]</div>
          </div>
        ) : data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="mono text-xs" style={{ color: '#2a3a5a' }}>NO CANDIDATES TODAY</div>
          </div>
        ) : (
          <div className="overflow-auto" style={{ maxHeight: '520px' }}>
            <table className="w-full text-sm">
              <thead style={{ position: 'sticky', top: 0, background: '#0a1020', zIndex: 1 }}>
                <tr style={{ borderBottom: '1px solid #1a2540' }}>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>RANK</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>代號</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>名稱</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>類別</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>分數</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>評級</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>訊號</th>
                </tr>
              </thead>
              <tbody>
                {data.map((row, i) => {
                  const isSelected = row.symbol === selectedSymbol
                  return (
                    <tr
                      key={row.symbol}
                      className="candidate-row"
                      style={{
                        borderBottom: '1px solid #0d1426',
                        background: isSelected ? 'rgba(0,212,255,0.06)' : undefined,
                        borderLeft: isSelected ? '2px solid #00d4ff' : '2px solid transparent',
                      }}
                      onClick={() => onSelect(row.symbol)}
                    >
                      <td className="py-2.5 px-2">
                        <span className="mono text-xs" style={{ color: '#4a6080' }}>#{row.rank}</span>
                      </td>
                      <td className="py-2.5 px-2">
                        <span className="mono text-sm font-bold" style={{ color: isSelected ? '#00d4ff' : '#c8daf0' }}>{row.symbol}</span>
                      </td>
                      <td className="py-2.5 px-2">
                        <span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.85rem' }}>{row.name || '—'}</span>
                      </td>
                      <td className="py-2.5 px-2">
                        <span className="mono text-xs" style={{ color: '#2a3a5a', fontSize: '0.7rem' }}>{row.industry_category || '—'}</span>
                      </td>
                      <td className="py-2.5 px-2" style={{ minWidth: '100px' }}>
                        <ScoreBar score={row.score} />
                      </td>
                      <td className="py-2.5 px-2">
                        <RatingBadge rating={row.rating} />
                      </td>
                      <td className="py-2.5 px-2">
                        <SignalBadge signalType={row.signal_type} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
