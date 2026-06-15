import React from 'react'

// 分析師標籤（與其他面板一致）
const SKILL_META = {
  'strat-vcp': { label: 'VCP突破', color: '#00ff88' },
  'strat-5-10-20': { label: '5-10-20', color: '#00d4ff' },
  'strat-spring': { label: '破支撐拉回', color: '#2dd4bf' },
  'strat-bb-trend': { label: '布林趨勢續抱', color: '#818cf8' },
  'strat-bb-breakout': { label: '布林開口突破', color: '#f59e0b' },
  'ml-logreg': { label: 'ML預測', color: '#ff6ec7' },
}

function SkillCell({ skill }) {
  const m = SKILL_META[skill] || { label: skill || '—', color: '#8ba3c7' }
  return (
    <span className="mono text-xs px-1.5 py-0.5 rounded-sm" style={{
      background: `${m.color}14`, border: `1px solid ${m.color}55`, color: m.color,
      fontFamily: 'Noto Sans TC', whiteSpace: 'nowrap',
    }}>{m.label}</span>
  )
}

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
  // 進場訊號中文化：A/B/C 為 5-10-20 進場型態；其餘走策略專屬訊號
  const labels = {
    A: '突破A', B: '回測B', C: '站回C',
    breakout: '開口突破', spring: '破支撐拉回', ml: 'ML看多',
  }
  const style = colors[signalType] || { bg: 'rgba(139,163,199,0.12)', border: 'rgba(139,163,199,0.4)', color: '#8ba3c7' }
  return (
    <span className="mono text-xs px-2 py-0.5 rounded-sm" style={{ background: style.bg, border: `1px solid ${style.border}`, color: style.color, fontFamily: 'Noto Sans TC', whiteSpace: 'nowrap' }}>
      {labels[signalType] || signalType}
    </span>
  )
}

export default function CandidatesPanel({ data, loading, error, selectedSymbol, onSelect }) {
  return (
    <div className="panel rounded-sm h-full flex flex-col" style={{ minHeight: '280px' }}>
      <div className="p-4 flex-1 flex flex-col min-h-0">
        <div className="section-header text-sm mb-4">
          <span style={{ color: '#00d4ff' }}>◆</span>
          綜合排行榜
          <span className="text-xs" style={{ color: '#4a6080', fontFamily: 'Noto Sans TC' }}>6 位分析師</span>
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
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>分析師</th>
                  <th className="mono text-left pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>分數</th>
                  <th className="mono text-center pb-2 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>推薦數</th>
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
                        <SkillCell skill={row.skill} />
                      </td>
                      <td className="py-2.5 px-2" style={{ minWidth: '100px' }}>
                        <ScoreBar score={row.score} />
                      </td>
                      <td className="py-2.5 px-2 text-center">
                        <span className="mono text-sm font-bold" style={{ color: Number(row.n_skills) >= 2 ? '#ffd700' : '#8ba3c7' }}>
                          {row.n_skills || 1}{Number(row.n_skills) >= 2 ? '★' : ''}
                        </span>
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
