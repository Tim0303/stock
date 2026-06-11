import React from 'react'

// 四位價量型分析師主題（與 AnalystPicksPanel 一致）
const SKILL_META = {
  'strat-5-10-20': { label: '5-10-20 順勢', accent: '#00d4ff' },
  'strat-spring': { label: '破支撐拉回', accent: '#ffb800' },
  'strat-bb-trend': { label: '布林趨勢續抱', accent: '#818cf8' },
  'strat-vcp': { label: 'VCP 突破', accent: '#00ff88' },
}
const SKILL_ORDER = ['strat-5-10-20', 'strat-spring', 'strat-bb-trend', 'strat-vcp']

function fmt(n, d = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(d)
}

function scanTimeLabel(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleTimeString('zh-TW', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Taipei',
    })
  } catch {
    return null
  }
}

function SkillCard({ skill, rows, onSelect, selectedSymbol }) {
  const meta = SKILL_META[skill] || { label: skill, accent: '#4a6080' }
  return (
    <div className="rounded-sm" style={{ background: '#0a1020', border: '1px solid #15203a', borderTop: `2px solid ${meta.accent}` }}>
      <div className="px-3 py-2 flex items-center justify-between" style={{ borderBottom: '1px solid #11192e' }}>
        <span className="mono text-xs font-bold" style={{ color: meta.accent }}>{meta.label}</span>
        <span className="mono text-xs" style={{ color: '#4a6080' }}>{rows.length} 檔</span>
      </div>
      {rows.length === 0 ? (
        <div className="flex items-center justify-center py-6">
          <span className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>今日無訊號</span>
        </div>
      ) : (
        <div className="overflow-auto" style={{ maxHeight: '300px' }}>
          <table className="w-full text-sm">
            <tbody>
              {rows.map((row) => {
                const isSel = row.symbol === selectedSymbol
                return (
                  <tr
                    key={row.symbol}
                    className="candidate-row"
                    style={{
                      borderBottom: '1px solid #0d1426', cursor: 'pointer',
                      background: isSel ? `${meta.accent}10` : undefined,
                      borderLeft: isSel ? `2px solid ${meta.accent}` : '2px solid transparent',
                    }}
                    onClick={() => onSelect && onSelect(row.symbol)}
                  >
                    <td className="py-2 px-2" style={{ whiteSpace: 'nowrap' }}>
                      <span className="mono text-sm font-bold" style={{ color: isSel ? meta.accent : '#c8daf0' }}>{row.symbol}</span>
                      <span className="ml-1.5" style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.78rem' }}>{row.name || ''}</span>
                    </td>
                    <td className="py-2 px-2 text-right">
                      <span className="mono text-sm font-bold" style={{ color: Number(row.score) >= 80 ? '#00ff88' : Number(row.score) >= 60 ? '#00d4ff' : '#ffb800' }}>
                        {row.score == null ? '—' : Math.round(row.score)}
                      </span>
                      {row.signal_type && (
                        <span className="mono ml-1.5" style={{ color: meta.accent, fontSize: '0.68rem' }}>{row.signal_type}</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-right" style={{ whiteSpace: 'nowrap' }}>
                      <span className="mono text-xs" style={{ color: '#8ba3c7' }}>{fmt(row.close)}</span>
                      {row.target_price != null && (
                        <span className="mono text-xs" style={{ color: '#00ff88' }}> →{fmt(row.target_price)}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function EodSignalsPanel({ data = [], scanTime, loading, error, onSelect, selectedSymbol }) {
  const bySkill = SKILL_ORDER.reduce((acc, s) => { acc[s] = []; return acc }, {})
  for (const row of data) {
    if (!bySkill[row.skill]) bySkill[row.skill] = []
    bySkill[row.skill].push(row)
  }
  const tLabel = scanTimeLabel(scanTime)

  return (
    <div className="panel rounded-sm" style={{ minHeight: '160px' }}>
      <div className="p-4">
        <div className="section-header text-sm mb-3 flex items-center gap-2">
          <span style={{ color: '#ff6ec7' }}>◆</span>
          尾盤即時訊號
          <span className="mono text-xs" style={{ color: '#4a6080' }}>
            {loading && !data.length
              ? 'SCANNING...'
              : tLabel
                ? `掃描於 ${tLabel} · ${data.length} 檔候選`
                : `${data.length} 檔候選`}
          </span>
          <span className="mono text-xs ml-auto" style={{ color: '#2a3a5a' }}>盤中即時報價試算 · 預覽不記錄</span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {!loading && !scanTime && data.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <div className="mono text-2xl" style={{ color: '#1a2540' }}>◯</div>
            <div className="text-xs" style={{ color: '#2a3a5a', fontFamily: 'Noto Sans TC' }}>今日尚未掃描（每日 13:10 盤中觸發）</div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
            {SKILL_ORDER.map((skill) => (
              <SkillCard key={skill} skill={skill} rows={bySkill[skill] || []} onSelect={onSelect} selectedSymbol={selectedSymbol} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
