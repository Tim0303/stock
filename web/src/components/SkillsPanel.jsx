import React from 'react'

const FAMILY_LABELS = {
  'strat-5-10-20': { label: '5·10·20 順勢', color: '#00ff88' },
  'strat-box': { label: '箱型區間', color: '#ffa500' },
  'strat-vcp': { label: 'VCP 突破', color: '#00d4ff' },
  'baseline-momentum': { label: '動能對照', color: '#b38fd4' },
  'ml-logreg': { label: 'ML 預測', color: '#5a8fd4' },
}

function ChampionRow({ family, version, params, n_predictions, win_rate }) {
  const meta = FAMILY_LABELS[family] || { label: family, color: '#4a6080' }
  const wr = win_rate !== null && win_rate !== undefined ? (win_rate * 100).toFixed(0) : null
  return (
    <div
      className="flex items-center justify-between py-2 px-3 rounded-sm"
      style={{ background: 'rgba(15,25,50,0.6)', borderLeft: `3px solid ${meta.color}` }}
    >
      <div>
        <div className="text-sm font-bold" style={{ color: meta.color, fontFamily: 'Noto Sans TC' }}>
          {meta.label}
        </div>
        <div className="mono text-xs mt-0.5" style={{ color: '#4a6080' }}>
          v{version} · 持有 {params?.horizon_days ?? '—'} 日 · 門檻 {params?.enter_threshold ?? '—'}
        </div>
      </div>
      <div className="text-right">
        <span
          className="mono text-xs px-2 py-0.5 rounded-sm"
          style={{ background: 'rgba(255,215,0,0.1)', border: '1px solid rgba(255,215,0,0.4)', color: '#ffd700' }}
        >
          ◆ 冠軍
        </span>
        <div className="mono text-xs mt-1" style={{ color: '#4a6080' }}>
          {n_predictions ?? 0} 筆
          {wr !== null && <span style={{ color: '#00ff88' }}> · 勝率 {wr}%</span>}
        </div>
      </div>
    </div>
  )
}

export default function SkillsPanel({ data, loading, error }) {
  const champions = (data || []).filter(s => s.status === 'champion')

  return (
    <div className="panel rounded-sm h-full">
      <div className="p-4">
        <div className="section-header text-sm mb-3">
          <span style={{ color: '#00d4ff' }}>◆</span>
          冠軍技能
          <span className="mono text-xs" style={{ color: '#4a6080' }}>SKILLS</span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {loading && !(data || []).length ? (
          <div className="flex items-center justify-center py-8">
            <div className="mono text-sm" style={{ color: '#1f3060' }}>[ LOADING... ]</div>
          </div>
        ) : champions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="mono text-xs" style={{ color: '#2a3a5a' }}>NO CHAMPION</div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {champions.map(s => <ChampionRow key={`${s.family}-${s.version}`} {...s} />)}
          </div>
        )}
      </div>
    </div>
  )
}
