import React, { useState } from 'react'

// 每位分析師一個主題色，做視覺區分
const ANALYST_THEME = {
  'strat-vcp':          { accent: '#00ff88', glow: 'rgba(0,255,136' },
  'strat-5-10-20':      { accent: '#00d4ff', glow: 'rgba(0,212,255' },
  'strat-box':          { accent: '#b38fd4', glow: 'rgba(179,143,212' },
  'strat-spring':       { accent: '#2dd4bf', glow: 'rgba(45,212,191' },
  'strat-bb-trend':     { accent: '#818cf8', glow: 'rgba(129,140,248' },
  'strat-bb-breakout':  { accent: '#f59e0b', glow: 'rgba(245,158,11' },
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

// 交易計畫：壓力目標(+%) + 停損
function TradePlanCell({ extra }) {
  if (!extra || extra.target_price === null || extra.target_price === undefined) {
    return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>
  }
  return (
    <div className="mono text-xs leading-tight whitespace-nowrap">
      <div style={{ color: '#00ff88' }}>
        🎯{fmtNum(extra.target_price, 1)}
        <span style={{ color: '#8ba3c7' }}> +{fmtNum(extra.target_pct, 1)}%</span>
      </div>
      <div style={{ color: '#ff6b81' }}>🛑{fmtNum(extra.stop_price, 1)}</div>
    </div>
  )
}

// 各分析師特有欄位的呈現
function ExtraCell({ skill, extra }) {
  if (!extra) return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>

  if (skill === 'strat-vcp') {
    const isBreakout = extra.status === '剛突破'
    return (
      <div className="flex items-center justify-center gap-2">
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

  if (skill === 'strat-5-10-20' || skill === 'strat-spring') {
    return <TradePlanCell extra={extra} />
  }

  return <span className="mono text-xs" style={{ color: '#1e2d4a' }}>—</span>
}

function AnalystCard({ analyst, onSelect, expanded = false }) {
  const theme = ANALYST_THEME[analyst.skill] || DEFAULT_THEME
  const accent = theme.accent
  const fmtP = (v, d = 1) => (v === null || v === undefined ? '—' : fmtNum(v, d))
  const planCols =
    (analyst.skill === 'strat-5-10-20' || analyst.skill === 'strat-spring') ? [
      { header: '進場', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{fmtP(p.extra?.entry_price)}</span> },
      { header: '目標', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#00ff88' }}>{fmtP(p.extra?.target_price)}</span> },
      { header: '目標%', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{p.extra?.target_pct != null ? `+${fmtNum(p.extra.target_pct, 1)}%` : '—'}</span> },
      { header: '停損', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#ff6b81' }}>{fmtP(p.extra?.stop_price)}</span> },
    ] : analyst.skill === 'strat-bb-trend' ? [
      { header: '進場', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{fmtP(p.extra?.entry_price, 2)}</span> },
      { header: '停損', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#ff6b81' }}>{fmtP(p.extra?.stop_price, 2)}</span> },
      { header: '出場', align: 'center', cell: () => <span className="text-xs" style={{ color: '#818cf8', fontFamily: 'Noto Sans TC', whiteSpace: 'nowrap' }}>趨勢續抱·破20MA</span> },
    ] : analyst.skill === 'strat-bb-breakout' ? [
      { header: '進場', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{fmtP(p.extra?.entry_price, 2)}</span> },
      { header: '量比', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#f59e0b' }}>{p.extra?.vol_ratio != null ? `${fmtNum(p.extra.vol_ratio, 1)}x` : '—'}</span> },
      { header: '開口', align: 'right', cell: (p) => <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{p.extra?.bw_ratio != null ? `${fmtNum(p.extra.bw_ratio, 1)}x` : '—'}</span> },
      { header: '出場', align: 'center', cell: () => <span className="text-xs" style={{ color: '#f59e0b', fontFamily: 'Noto Sans TC', whiteSpace: 'nowrap' }}>跌破20MA</span> },
    ] : analyst.skill === 'strat-vcp' ? [
      { header: '狀態', align: 'left', cell: (p) => <ExtraCell skill={analyst.skill} extra={p.extra} /> },
    ] : []
  const columns = [
    { header: '代號', align: 'left', cell: (p) => <span className="mono text-sm font-bold" style={{ color: '#c8daf0' }}>{p.symbol}</span> },
    { header: '名稱', align: 'left', cell: (p) => <span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.82rem' }}>{p.name || '—'}</span> },
    { header: '分數', align: 'right', cell: (p) => <ScoreCell score={p.score} accent={accent} /> },
    ...planCols,
  ]

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
          <div className="overflow-auto flex-1" style={{ maxHeight: '212px' }}>
            <table className="w-full text-sm">
              <thead style={{ position: 'sticky', top: 0, background: '#0a1020', zIndex: 1 }}>
                <tr style={{ borderBottom: '1px solid #1a2540' }}>
                  {columns.map((c, i) => (
                    <th key={i} className="mono pb-1.5 text-xs text-center" style={{ color: '#4a6080', fontWeight: 400 }}>{c.header}</th>
                  ))}
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
                    {columns.map((c, i) => (
                      <td key={i} className="py-2 px-1 text-center">{c.cell(p)}</td>
                    ))}
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

function MarketBadge({ market }) {
  if (!market) return null
  const ok = market.market_ok
  return (
    <span
      className="mono text-xs px-2 py-0.5 rounded-sm"
      style={{
        background: ok ? 'rgba(0,255,136,0.10)' : 'rgba(255,107,129,0.12)',
        border: `1px solid ${ok ? 'rgba(0,255,136,0.4)' : 'rgba(255,107,129,0.45)'}`,
        color: ok ? '#00ff88' : '#ff6b81',
        whiteSpace: 'nowrap',
      }}
      title="大盤寬度＝% 個股站上 20MA；<50% 視為空頭。僅作風險提示，策略仍照常開倉"
    >
      {ok ? '◉' : '◯'} 大盤寬度 {market.breadth_pct}% {ok ? '健康' : '偏弱·留意風險'}
    </span>
  )
}

// 分析師 tab 切換：上方 tab 列、下方顯示選中分析師推薦表
function AnalystTabs({ analysts, onSelect }) {
  const [activeSkill, setActiveSkill] = useState(null)
  const active = analysts.find((a) => a.skill === activeSkill) || analysts[0]
  if (!active) return null
  return (
    <div>
      <div className="flex gap-1.5 mb-3 flex-wrap">
        {analysts.map((a) => {
          const theme = ANALYST_THEME[a.skill] || DEFAULT_THEME
          const isActive = a.skill === active.skill
          return (
            <button
              key={a.skill}
              onClick={() => setActiveSkill(a.skill)}
              className="mono text-xs px-3 py-1.5 rounded-sm flex items-center gap-2 transition-colors"
              style={{
                cursor: 'pointer',
                background: isActive ? `${theme.glow},0.14)` : 'rgba(15,25,50,0.5)',
                border: `1px solid ${isActive ? `${theme.glow},0.55)` : '#1a2540'}`,
                borderBottom: `2px solid ${isActive ? theme.accent : '#1a2540'}`,
                color: isActive ? theme.accent : '#8ba3c7',
              }}
            >
              <span style={{ fontFamily: 'Noto Sans TC', fontWeight: isActive ? 700 : 400 }}>{a.label}</span>
              <span
                className="px-1.5 rounded-sm"
                style={{ background: isActive ? `${theme.glow},0.18)` : 'rgba(0,0,0,0.25)', color: isActive ? theme.accent : '#4a6080' }}
              >
                {a.count}
              </span>
            </button>
          )
        })}
      </div>
      <AnalystCard analyst={active} onSelect={onSelect} expanded />
    </div>
  )
}

export default function AnalystPicksPanel({ analysts = [], loading, computing, error, onSelect, market }) {
  const total = analysts.reduce((s, a) => s + (a.count || 0), 0)
  const noSnapshot = analysts.length === 0

  return (
    <div>
      <div className="section-header text-sm mb-3">
        <span style={{ color: '#00d4ff' }}>◆</span>
        分析師推薦
        <span className="mono text-xs" style={{ color: '#4a6080' }}>
          {loading && noSnapshot ? 'LOADING...' : noSnapshot && computing ? 'COMPUTING...' : `共 ${total} 檔 · ${analysts.length} 位分析師`}
        </span>
        <span className="ml-auto"><MarketBadge market={market} /></span>
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
        <AnalystTabs analysts={analysts} onSelect={onSelect} />
      )}
    </div>
  )
}
