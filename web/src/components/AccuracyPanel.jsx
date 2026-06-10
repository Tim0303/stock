import React from 'react'

const SKILL_LABELS = {
  'baseline-momentum': { label: 'MOMENTUM', short: 'MOM', color: '#b38fd4' },
  'ml-logreg': { label: 'ML LOGREG', short: 'ML', color: '#00d4ff' },
  'strat-5-10-20': { label: '5·10·20 MA', short: 'MA', color: '#00ff88' },
}

function StatLine({ label, value, unit = '', color = '#8ba3c7', highlight = false }) {
  return (
    <div className="flex items-center justify-between py-1" style={{ borderBottom: '1px solid #0d1426' }}>
      <span className="mono text-xs" style={{ color: '#4a6080' }}>{label}</span>
      <span
        className="mono text-sm font-bold"
        style={{ color: highlight ? color : '#8ba3c7' }}
      >
        {value !== null && value !== undefined ? `${value}${unit}` : <span style={{ color: '#1e2d4a' }}>—</span>}
      </span>
    </div>
  )
}

function AccuracyCard({ skill, n_evaluated, win_rate, avg_return, profit_factor }) {
  const meta = SKILL_LABELS[skill] || { label: skill, short: '?', color: '#4a6080' }
  const hasData = n_evaluated > 0

  return (
    <div
      className="stat-card rounded-sm p-3"
      style={{
        background: 'rgba(15,25,50,0.8)',
        border: `1px solid ${meta.color}22`,
        borderTop: `2px solid ${meta.color}`,
      }}
    >
      {/* Card header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded-sm flex items-center justify-center mono text-xs font-bold"
            style={{ background: `${meta.color}15`, border: `1px solid ${meta.color}44`, color: meta.color }}
          >
            {meta.short}
          </div>
          <span className="mono text-xs font-bold tracking-widest" style={{ color: meta.color }}>
            {meta.label}
          </span>
        </div>
        <span className="mono text-xs px-2 py-0.5 rounded-sm" style={{ background: 'rgba(0,0,0,0.3)', color: '#2a3a5a' }}>
          n={n_evaluated ?? 0}
        </span>
      </div>

      {!hasData ? (
        <div className="py-4 text-center">
          <div className="mono text-xs" style={{ color: '#1a2540' }}>◯ ◯ ◯</div>
          <div className="mono text-xs mt-1" style={{ color: '#2a3a5a' }}>學習中</div>
          <div className="text-xs mt-1" style={{ color: '#1e2d4a', fontFamily: 'Noto Sans TC' }}>尚無到期評分</div>
        </div>
      ) : (
        <div>
          <StatLine
            label="WIN RATE"
            value={win_rate !== null ? (win_rate * 100).toFixed(1) : null}
            unit="%"
            color={meta.color}
            highlight={true}
          />
          <StatLine
            label="AVG RETURN"
            value={avg_return !== null ? (avg_return * 100).toFixed(2) : null}
            unit="%"
            color={avg_return >= 0 ? '#00ff88' : '#ff3366'}
            highlight={true}
          />
          <StatLine
            label="PROFIT FACTOR"
            value={profit_factor !== null ? profit_factor.toFixed(2) : null}
            color={profit_factor >= 1 ? '#00ff88' : '#ff3366'}
            highlight={true}
          />
        </div>
      )}
    </div>
  )
}

const DEFAULT_SKILLS = [
  { skill: 'strat-5-10-20', n_evaluated: 0, win_rate: null, avg_return: null, profit_factor: null },
  { skill: 'ml-logreg', n_evaluated: 0, win_rate: null, avg_return: null, profit_factor: null },
]

export default function AccuracyPanel({ data, loading, error }) {
  // Merge fetched data with defaults to always show all 3 cards
  const displayData = DEFAULT_SKILLS.map(def => {
    const found = data.find(d => d.skill === def.skill)
    return found || def
  })

  return (
    <div className="panel rounded-sm h-full">
      <div className="p-4">
        <div className="section-header text-sm mb-4">
          <span style={{ color: '#00d4ff' }}>◆</span>
          策略準確率
          <span className="mono text-xs" style={{ color: '#4a6080' }}>ACCURACY</span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {loading && !data.length ? (
          <div className="flex items-center justify-center py-8">
            <div className="mono text-sm" style={{ color: '#1f3060' }}>[ LOADING... ]</div>
          </div>
        ) : (
          <div className="flex flex-col gap-3 overflow-y-auto" style={{ maxHeight: '420px' }}>
            {displayData.map(item => (
              <AccuracyCard key={item.skill} {...item} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
