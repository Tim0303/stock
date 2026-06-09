import React from 'react'

function ParamItem({ label, value }) {
  return (
    <div className="flex items-center justify-between py-1" style={{ borderBottom: '1px solid #0d1426' }}>
      <span className="mono text-xs" style={{ color: '#4a6080' }}>{label}</span>
      <span className="mono text-xs" style={{ color: '#00d4ff' }}>{String(value)}</span>
    </div>
  )
}

function StatusBadge({ status }) {
  const map = {
    champion: { bg: 'rgba(255,215,0,0.1)', border: 'rgba(255,215,0,0.4)', color: '#ffd700', label: '◆ CHAMPION' },
    active: { bg: 'rgba(0,255,136,0.1)', border: 'rgba(0,255,136,0.3)', color: '#00ff88', label: '● ACTIVE' },
    retired: { bg: 'rgba(74,96,128,0.1)', border: 'rgba(74,96,128,0.3)', color: '#4a6080', label: '○ RETIRED' },
  }
  const s = map[status] || map.active
  return (
    <span
      className="mono text-xs px-2 py-0.5 rounded-sm"
      style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color }}
    >
      {s.label}
    </span>
  )
}

function SkillCard({ family, version, status, params, n_predictions, win_rate }) {
  const keyParams = [
    { label: 'ENTER_THRESHOLD', value: params?.enter_threshold ?? '—' },
    { label: 'HORIZON_DAYS', value: params?.horizon_days ?? '—' },
    { label: 'MA_FAST / SLOW', value: `${params?.ma_fast ?? '—'} / ${params?.ma_slow ?? '—'}` },
    { label: 'VOL_RATIO_MIN', value: params?.vol_ratio_min ?? '—' },
    { label: 'WATCH_THRESHOLD', value: params?.watch_threshold ?? '—' },
    { label: 'CHIP_OVERLAY', value: String(params?.chip_overlay ?? false) },
  ]

  return (
    <div
      className="stat-card rounded-sm p-4"
      style={{
        background: 'rgba(15,25,50,0.8)',
        border: '1px solid rgba(255,215,0,0.15)',
        borderTop: '2px solid #ffd700',
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="mono text-sm font-bold tracking-wider" style={{ color: '#ffd700' }}>
            {family}
          </div>
          <div className="mono text-xs mt-0.5" style={{ color: '#4a6080' }}>
            v{version} · {n_predictions ?? 0} predictions
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Params */}
      <div className="mt-3">
        <div className="mono text-xs mb-2" style={{ color: '#2a3a5a', letterSpacing: '0.1em' }}>— PARAMS —</div>
        {keyParams.map(p => <ParamItem key={p.label} {...p} />)}
      </div>

      {/* MA signals enabled */}
      {params && (
        <div className="mt-3 flex gap-2">
          {['A', 'B', 'C'].map(sig => {
            const enabled = params[`enable_signal_${sig}`]
            return (
              <div
                key={sig}
                className="mono text-xs px-2 py-1 rounded-sm flex-1 text-center"
                style={{
                  background: enabled ? 'rgba(0,212,255,0.1)' : 'rgba(26,37,64,0.5)',
                  border: `1px solid ${enabled ? 'rgba(0,212,255,0.3)' : '#1a2540'}`,
                  color: enabled ? '#00d4ff' : '#2a3a5a',
                }}
              >
                SIG_{sig}
              </div>
            )
          })}
        </div>
      )}

      {win_rate !== null && win_rate !== undefined && (
        <div className="mt-3 pt-2" style={{ borderTop: '1px solid #1a2540' }}>
          <div className="flex justify-between">
            <span className="mono text-xs" style={{ color: '#4a6080' }}>WIN RATE</span>
            <span className="mono text-sm font-bold" style={{ color: '#00ff88' }}>
              {(win_rate * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SkillsPanel({ data, loading, error }) {
  const champions = data.filter(s => s.status === 'champion')
  const others = data.filter(s => s.status !== 'champion')

  return (
    <div className="panel rounded-sm h-full">
      <div className="p-4">
        <div className="section-header text-sm mb-4">
          <span style={{ color: '#00d4ff' }}>◆</span>
          技能績效
          <span className="mono text-xs" style={{ color: '#4a6080' }}>SKILLS</span>
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
        ) : data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="mono text-xs" style={{ color: '#2a3a5a' }}>NO SKILLS REGISTERED</div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {champions.map(s => <SkillCard key={`${s.family}-${s.version}`} {...s} />)}
            {others.map(s => <SkillCard key={`${s.family}-${s.version}`} {...s} />)}
          </div>
        )}
      </div>
    </div>
  )
}
