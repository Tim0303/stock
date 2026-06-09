import React from 'react'

// 每位分析師一個主題色，做視覺區分
const ANALYST_THEME = {
  'strat-vcp':          { accent: '#00ff88', glow: 'rgba(0,255,136' },
  'strat-5-10-20':      { accent: '#00d4ff', glow: 'rgba(0,212,255' },
  'strat-box':          { accent: '#b38fd4', glow: 'rgba(179,143,212' },
  'baseline-momentum':  { accent: '#ffb800', glow: 'rgba(255,184,0' },
  'ml-logreg':          { accent: '#ff6ec7', glow: 'rgba(255,110,199' },
}

const DEFAULT_THEME = { accent: '#8ba3c7', glow: 'rgba(139,163,199' }

function fmtNum(v, digits = 1) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

function ScoreCell({ score, accent }) {
  const n = Number(score)
  return (
    <span className="mono text-sm font-bold" style={{ color: Number.isNaN(n) ? '#4a6080' : accent }}>
      {Number.isNaN(n) ? '—' : n.toFixed(1)}
    </span>
  )
}

// 各分析師特有欄位的呈現
function ExtraCell({ skill, extra }) {
  if (!extra) return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>

  if (skill === 'strat-vcp') {
    const isBreakout = extra.status === '剛突破'
    return (
      <div className="flex items-center gap-2">
        <span
          className="px-1.5 py-0.5 rounded-sm text-xs"
          style={{
            background: isBreakout ? 'rgba(0,255,136,0.12)' : 'rgba(255,184,0,0.12)',
            border: `1px solid ${isBreakout ? 'rgba(0,255,136,0.45)' : 'rgba(255,184,0,0.40)'}`,
            color: isBreakout ? '#00ff88' : '#ffb800',
            fontFamily: 'Noto Sans TC',
            whiteSpace: 'nowrap',
          }}
        >
          {extra.status || '—'}
        </span>
        <span className="mono text-xs" style={{ color: '#8ba3c7' }}>
          {fmtNum(extra.distance_pct, 2)}%
        </span>
      </div>
    )
  }

  if (skill === 'strat-5-10-20') {
    const st = extra.signal_type
    if (!st) return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>
    const colors = {
      A: { bg: 'rgba(0,212,255,0.15)', border: 'rgba(0,212,255,0.5)', color: '#00d4ff' },
      B: { bg: 'rgba(179,143,212,0.15)', border: 'rgba(179,143,212,0.5)', color: '#b38fd4' },
      C: { bg: 'rgba(255,215,0,0.12)', border: 'rgba(255,215,0,0.4)', color: '#ffd700' },
    }
    const s = colors[st] || colors.A
    return (
      <span className="mono text-xs px-2 py-0.5 rounded-sm" style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color }}>
        訊號{st}
      </span>
    )
  }

  return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>
}

function AnalystCard({ analyst, onSelect }) {
  const theme = ANALYST_THEME[analyst.skill] || DEFAULT_THEME
  const accent = theme.accent
  const hasExtra = analyst.skill === 'strat-vcp' || analyst.skill === 'strat-5-10-20'
  const extraHeader = analyst.skill === 'strat-vcp' ? '狀態 / 距樞紐' : analyst.skill === 'strat-5-10-20' ? '訊號' : null

  return (
    <div
      className="panel rounded-sm flex flex-col"
      style={{
        minHeight: '240px',
        borderTop: `2px solid ${accent}`,
        boxShadow: `inset 0 18px 28px -28px ${theme.glow},0.45)`,
      }}
    >
      <div className="p-3 flex flex-col h-full">
        {/* 卡片標題 */}
        <div className="flex items-baseline justify-between mb-1">
          <div className="flex items-center gap-2">
            <span style={{ color: accent }}>◆</span>
            <span className="text-sm font-bold" style={{ color: '#e8f1ff', fontFamily: 'Noto Sans TC' }}>
              {analyst.label}
            </span>
          </div>
          <span
            className="mono text-xs px-1.5 py-0.5 rounded-sm"
            style={{ color: accent, background: `${theme.glow},0.10)`, border: `1px solid ${theme.glow},0.30)` }}
          >
            {analyst.count} 檔
          </span>
        </div>
        <div className="mono text-xs mb-3" style={{ color: '#4a6080' }}>
          {analyst.skill} {analyst.as_of ? `· ${analyst.as_of}` : ''}
        </div>

        {/* 推薦表 / 空狀態 */}
        {(!analyst.picks || analyst.picks.length === 0) ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-2 py-6">
            <div className="mono text-xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>
              今日無推薦
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid #1a2540' }}>
                  <th className="mono text-left pb-1.5 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>代號</th>
                  <th className="mono text-left pb-1.5 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>名稱</th>
                  <th className="mono text-right pb-1.5 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>分數</th>
                  {hasExtra && (
                    <th className="mono text-left pb-1.5 pl-3 text-xs" style={{ color: '#4a6080', fontWeight: 400 }}>{extraHeader}</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {analyst.picks.map((p) => (
                  <tr
                    key={p.symbol}
                    className="candidate-row"
                    style={{ borderBottom: '1px solid #0d1426', cursor: onSelect ? 'pointer' : 'default' }}
                    onClick={onSelect ? () => onSelect(p.symbol) : undefined}
                  >
                    <td className="py-2 px-1">
                      <span className="mono text-sm font-bold" style={{ color: '#c8daf0' }}>{p.symbol}</span>
                    </td>
                    <td className="py-2 px-1">
                      <span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.82rem' }}>{p.name || '—'}</span>
                    </td>
                    <td className="py-2 px-1 text-right">
                      <ScoreCell score={p.score} accent={accent} />
                    </td>
                    {hasExtra && (
                      <td className="py-2 px-1 pl-3">
                        <ExtraCell skill={analyst.skill} extra={p.extra} />
                      </td>
                    )}
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

export default function AnalystPicksPanel({ analysts = [], loading, computing, error, onSelect }) {
  const total = analysts.reduce((s, a) => s + (a.count || 0), 0)
  const noSnapshot = analysts.length === 0

  return (
    <div>
      <div className="section-header text-sm mb-3">
        <span style={{ color: '#00d4ff' }}>◆</span>
        5 位分析師推薦
        <span className="mono text-xs" style={{ color: '#4a6080' }}>
          {loading && noSnapshot ? 'LOADING...' : noSnapshot && computing ? 'COMPUTING...' : `共 ${total} 檔 · ${analysts.length} 位分析師`}
        </span>
      </div>

      {error && (
        <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
          ERR: {error}
        </div>
      )}

      {noSnapshot && (loading || computing) ? (
        <div className="panel rounded-sm flex flex-col items-center justify-center py-16 gap-2">
          <div className="mono text-sm" style={{ color: '#1f3060' }}>[ 分析師快照計算中... ]</div>
          <div className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>
            首次載入策略 view 較久，稍後將自動顯示（每 30 秒重試）
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
          {analysts.map((a) => (
            <AnalystCard key={a.skill} analyst={a} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  )
}
