import React, { useState, useEffect, useMemo, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'

async function fetchIndicators(symbol, limit = 250) {
  const res = await fetch(`/api/indicators/${encodeURIComponent(symbol)}?limit=${limit}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchStrategy(symbol, limit = 250) {
  const res = await fetch(`/api/strategy/${encodeURIComponent(symbol)}?limit=${limit}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchSymbols() {
  const res = await fetch('/api/symbols?limit=5000')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

const RATING_COLORS = {
  buy: '#00ff88',
  watch: '#ffb800',
  skip: '#2a3a5a',
  avoid: '#ff3366',
}

// 5-10-20 進場訊號標記配色（與候選榜徽章一致）：A 突破=青 / B 回測=紫 / C 站回=金
const SIGNAL_COLORS = { A: '#00d4ff', B: '#b38fd4', C: '#ffd700' }

// 股價一律顯示到小數點後 2 位
function fmtPrice(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

// 均線設定（可逐條開關）：MA5=黃 / MA10=紫 / MA20=青（原 MA5 色）
const MA_CONFIG = [
  { key: 'ma5', name: 'MA5', color: '#ffb800' },
  { key: 'ma10', name: 'MA10', color: '#b38fd4' },
  { key: 'ma20', name: 'MA20', color: '#00d4ff' },
]

// 布林通道：中軌 = MA20，上下軌 = 中軌 ± 2σ（σ = 20 日收盤母體標準差），通道色靛
const BB_COLOR = '#818cf8'
const BB_PERIOD = 20
const BB_K = 2

function buildChartOption(indicators, strategy, showStrategy, maVisible, showBB) {
  if (!indicators || indicators.length === 0) return null

  // Sort chronologically
  const sorted = [...indicators].sort((a, b) => new Date(a.ts) - new Date(b.ts))
  const stratMap = {}
  if (strategy) {
    strategy.forEach(s => { stratMap[s.ts] = s })
  }

  const dates = sorted.map(d => d.ts.slice(0, 10))
  const candleData = sorted.map(d => [
    d.open != null ? +(+d.open).toFixed(2) : d.open,
    d.close != null ? +(+d.close).toFixed(2) : d.close,
    d.low != null ? +(+d.low).toFixed(2) : d.low,
    d.high != null ? +(+d.high).toFixed(2) : d.high,
  ])
  const volumes = sorted.map(d => d.volume)
  const ma5 = sorted.map(d => d.ma5 != null ? +d.ma5.toFixed(2) : null)
  const ma10 = sorted.map(d => d.ma10 != null ? +d.ma10.toFixed(2) : null)
  const ma20 = sorted.map(d => d.ma20 != null ? +d.ma20.toFixed(2) : null)

  // 布林通道上下軌（中軌沿用 MA20；σ 以中軌為中心，使通道恰好對稱於畫出的 MA20 線）
  const closes = sorted.map(d => (d.close != null ? +d.close : null))
  const bbUpper = []
  const bbLower = []
  for (let i = 0; i < sorted.length; i++) {
    const mid = ma20[i]
    if (i < BB_PERIOD - 1 || mid == null) { bbUpper.push(null); bbLower.push(null); continue }
    let sum = 0, ok = true
    for (let k = i - BB_PERIOD + 1; k <= i; k++) {
      const c = closes[k]
      if (c == null) { ok = false; break }
      sum += (c - mid) * (c - mid)
    }
    if (!ok) { bbUpper.push(null); bbLower.push(null); continue }
    const sd = Math.sqrt(sum / BB_PERIOD)
    bbUpper.push(+(mid + BB_K * sd).toFixed(2))
    bbLower.push(+(mid - BB_K * sd).toFixed(2))
  }
  // 通道填色用「下軌 + 厚度」堆疊（隱形線、只留 area）；上下軌另以實值虛線畫，tooltip 顯示真值
  const bbThickness = bbUpper.map((u, i) => (u == null || bbLower[i] == null ? null : +(u - bbLower[i]).toFixed(2)))

  // Strategy signal markers（A/C 進場訊號：放 K 棒下方、向上箭頭＝買點）
  const markPoints = []
  if (showStrategy && strategy) {
    sorted.forEach((d, i) => {
      const s = stratMap[d.ts]
      // 只標示真正的買訊（rating=buy）；avoid/skip/watch 的訊號不畫，避免把「追高被濾掉的 A」誤看成買點
      if (s && s.signal_type && s.rating === 'buy') {
        const col = SIGNAL_COLORS[s.signal_type] || '#00d4ff'
        markPoints.push({
          coord: [i, d.low * 0.985],
          value: s.signal_type,
          itemStyle: { color: col, borderColor: '#0a0f1e', borderWidth: 1 },
          label: { color: col },
        })
      }
    })
  }

  // Volume colors
  const volColors = sorted.map(d => d.close >= (d.open || d.close) ? 'rgba(255,51,102,0.6)' : 'rgba(0,255,136,0.6)')

  return {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 400,
    textStyle: { fontFamily: 'Share Tech Mono, monospace', fontSize: 11 },
    grid: [
      { left: 60, right: 16, top: 16, bottom: 140 },
      { left: 60, right: 16, top: 'auto', bottom: 48, height: 60 },
    ],
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: {
        backgroundColor: '#0a0f1e',
        borderColor: '#1f3060',
        color: '#8ba3c7',
        fontFamily: 'Share Tech Mono',
      },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(10,15,30,0.97)',
      borderColor: '#1f3060',
      padding: [8, 12],
      textStyle: { color: '#c8daf0', fontFamily: 'Share Tech Mono', fontSize: 13 },
      formatter(params) {
        if (!params || params.length === 0) return ''
        const date = params[0].axisValue
        let html = `<div style="color:#8ba3c7;margin-bottom:4px;font-size:13px">${date}</div>`
        params.forEach(p => {
          if (p.seriesName === 'K線') {
            const i = p.dataIndex
            // ★直接從原始 OHLC(sorted[i]) 讀，避免 ECharts candlestick 之 p.value 前綴索引造成開/收/高/低錯位
            const d = sorted[i] || {}
            const o = d.open != null ? +d.open : null
            const c = d.close != null ? +d.close : null
            const l = d.low != null ? +d.low : null
            const h = d.high != null ? +d.high : null
            const prevC = (i > 0 && sorted[i - 1] && sorted[i - 1].close != null) ? +sorted[i - 1].close : null
            const base = prevC != null ? prevC : o          // 當日漲幅以前一日收盤為基準（無前日則用開盤）
            const chg = c - base
            const pct = base ? (chg / base) * 100 : 0
            const color = chg >= 0 ? '#ff3366' : '#00ff88'   // 紅漲綠跌
            html += `<div style="font-size:14px;line-height:1.8;margin-top:2px">`
            html += `<span style="color:#8ba3c7">開</span> <b style="color:#e8f1ff">${fmtPrice(o)}</b>　<span style="color:#8ba3c7">收</span> <b style="color:${color}">${fmtPrice(c)}</b><br>`
            html += `<span style="color:#8ba3c7">高</span> ${fmtPrice(h)}　<span style="color:#8ba3c7">低</span> ${fmtPrice(l)}<br>`
            html += `<span style="color:#8ba3c7">當日漲幅</span> <b style="color:${color};font-size:15px">${chg >= 0 ? '+' : ''}${chg.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)</b>`
            html += `</div>`
          } else if (p.seriesName && p.seriesName.startsWith('MA')) {
            if (p.value != null) {
              html += `<div><span style="color:${p.color}">${p.seriesName}</span> ${p.value}</div>`
            }
          } else if (p.seriesName && p.seriesName.startsWith('布林')) {
            if (p.value != null) {
              html += `<div><span style="color:${p.color}">${p.seriesName}</span> ${p.value}</div>`
            }
          } else if (p.seriesName === '量' && p.value != null) {
            html += `<div style="color:#4a6080">VOL: ${(p.value / 1000).toFixed(0)}K</div>`
          }
        })
        // Strategy overlay
        const sortedEntry = sorted.find(d => d.ts.slice(0, 10) === date)
        if (showStrategy && sortedEntry) {
          const s = stratMap[sortedEntry.ts]
          if (s) {
            const rcolor = RATING_COLORS[s.rating] || '#8ba3c7'
            html += `<div style="margin-top:4px;border-top:1px solid #1a2540;padding-top:4px">`
            html += `<span style="color:${rcolor}">SCORE: ${s.score ?? '—'} | ${(s.rating || '').toUpperCase()}</span>`
            if (s.signal_type) html += ` <span style="color:#ffd700">SIG-${s.signal_type}</span>`
            html += `</div>`
          }
        }
        return html
      },
    },
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: '#1a2540' } },
        axisLabel: { color: '#4a6080', fontFamily: 'Share Tech Mono', fontSize: 10 },
        axisTick: { show: false },
        splitLine: { show: false },
        boundaryGap: true,
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLine: { lineStyle: { color: '#1a2540' } },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        boundaryGap: true,
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        position: 'left',
        scale: true,
        axisLine: { show: false },
        axisLabel: {
          color: '#4a6080',
          fontFamily: 'Share Tech Mono',
          fontSize: 10,
          formatter: v => v.toFixed(2),
        },
        splitLine: { lineStyle: { color: '#1a2540', type: 'dashed' } },
        axisTick: { show: false },
      },
      {
        type: 'value',
        gridIndex: 1,
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
        axisLine: { show: false },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: Math.max(0, 100 - (40 / sorted.length) * 100),
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 8,
        height: 24,
        backgroundColor: '#0a0f1e',
        borderColor: '#1a2540',
        fillerColor: 'rgba(0,212,255,0.06)',
        handleStyle: { color: '#00d4ff44', borderColor: '#00d4ff88' },
        textStyle: { color: '#4a6080', fontFamily: 'Share Tech Mono', fontSize: 9 },
        start: Math.max(0, 100 - (40 / sorted.length) * 100),
        end: 100,
      },
    ],
    series: [
      {
        name: 'K線',
        type: 'candlestick',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: candleData,
        barMaxWidth: 18,
        barMinWidth: 4,
        z: 6,
        itemStyle: {
          // 台股慣例：紅漲綠跌（color=收>=開 上漲、color0=下跌）
          color: '#ff3366',
          color0: '#00ff88',
          borderColor: '#ff3366',
          borderColor0: '#00ff88',
          borderWidth: 1.5,
        },
        markPoint: markPoints.length > 0 ? {
          symbol: 'triangle',
          symbolSize: 20,
          data: markPoints,
          label: {
            show: true,
            position: 'bottom',
            distance: 3,
            formatter: p => p.value,
            fontSize: 13,
            fontWeight: 'bold',
            fontFamily: 'Share Tech Mono',
          },
        } : undefined,
      },
      // 布林通道：填色（下軌+厚度堆疊，隱形線）+ 上下軌虛線（實值，供 tooltip）
      ...(showBB ? [
        {
          name: '_bbBase', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: bbLower, stack: 'bb', symbol: 'none',
          lineStyle: { opacity: 0 }, z: 2, silent: true, tooltip: { show: false },
        },
        {
          name: '_bbFill', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: bbThickness, stack: 'bb', symbol: 'none',
          lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(129,140,248,0.07)' },
          z: 2, silent: true, tooltip: { show: false },
        },
        {
          name: '布林上軌', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: bbUpper, symbol: 'none',
          lineStyle: { color: BB_COLOR, width: 1, opacity: 0.6, type: 'dashed' }, z: 3,
        },
        {
          name: '布林下軌', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
          data: bbLower, symbol: 'none',
          lineStyle: { color: BB_COLOR, width: 1, opacity: 0.6, type: 'dashed' }, z: 3,
        },
      ] : []),
      // 均線：依 MA_CONFIG 順序，只畫「開關開啟」的那幾條
      ...MA_CONFIG.filter(m => !maVisible || maVisible[m.key]).map(m => ({
        name: m.name,
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: { ma5, ma10, ma20 }[m.key],
        smooth: false,
        symbol: 'none',
        lineStyle: { color: m.color, width: 1.2, opacity: 0.85 },
        z: 4,
      })),
      {
        name: '量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params) => volColors[params.dataIndex],
        },
        barMaxWidth: 8,
      },
    ],
  }
}

export default function ChartPanel({ symbol, defaultSymbol = '2330.TW' }) {
  const [indicators, setIndicators] = useState([])
  const [strategy, setStrategy] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showStrategy, setShowStrategy] = useState(true)
  // 均線開關（預設全開）
  const [maVisible, setMaVisible] = useState({ ma5: true, ma10: true, ma20: true })
  // 布林通道開關（預設開）
  const [showBB, setShowBB] = useState(true)

  // 個股查詢：本面板自管「目前顯示的代號」
  const [activeSymbol, setActiveSymbol] = useState(symbol || defaultSymbol)
  const [queryInput, setQueryInput] = useState(symbol || defaultSymbol)
  const [symbolList, setSymbolList] = useState([])

  // 外部（候選榜/分析師）點選時，同步到本面板
  useEffect(() => {
    if (symbol) {
      setActiveSymbol(symbol)
      setQueryInput(symbol)
    }
  }, [symbol])

  // 載入 symbols 清單供 datalist 自動完成（端點不存在時靜默略過）
  useEffect(() => {
    fetchSymbols()
      .then(r => setSymbolList(r.data || []))
      .catch(() => setSymbolList([]))
  }, [])

  const submitQuery = useCallback(() => {
    const v = (queryInput || '').trim()
    if (v) setActiveSymbol(v)
  }, [queryInput])

  const loadData = useCallback(async (sym) => {
    if (!sym) return
    setLoading(true)
    setError(null)
    try {
      const [indRes, stratRes] = await Promise.allSettled([
        fetchIndicators(sym, 250),
        fetchStrategy(sym, 250),
      ])
      if (indRes.status === 'fulfilled') setIndicators(indRes.value.data || [])
      else setError(indRes.reason?.message)
      if (stratRes.status === 'fulfilled') setStrategy(stratRes.value.data || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData(activeSymbol)
  }, [activeSymbol, loadData])

  const option = useMemo(
    () => buildChartOption(indicators, strategy, showStrategy, maVisible, showBB),
    [indicators, strategy, showStrategy, maVisible, showBB]
  )

  // Latest price info
  const latest = useMemo(() => {
    if (!indicators.length) return null
    const sorted = [...indicators].sort((a, b) => new Date(b.ts) - new Date(a.ts))
    return sorted[0]
  }, [indicators])

  const latestStrat = useMemo(() => {
    if (!strategy.length) return null
    const sorted = [...strategy].sort((a, b) => new Date(b.ts) - new Date(a.ts))
    return sorted[0]
  }, [strategy])

  // 目前代號的公司名稱（由 symbols 清單查）
  const activeName = useMemo(() => {
    const m = symbolList.find((s) => s.symbol === activeSymbol)
    return m?.name || ''
  }, [symbolList, activeSymbol])

  // 最新交易日：開盤/收盤/當日漲幅（漲幅以前一日收盤為基準）
  const dayInfo = useMemo(() => {
    if (!indicators.length) return null
    const sorted = [...indicators].sort((a, b) => new Date(b.ts) - new Date(a.ts))
    const cur = sorted[0], prev = sorted[1]
    const open = cur?.open != null ? +cur.open : null
    const close = cur?.close != null ? +cur.close : null
    const pc = prev?.close != null ? +prev.close : null
    const chg = (close != null && pc != null) ? close - pc : null
    const pct = (chg != null && pc) ? (chg / pc) * 100 : null
    return { open, close, chg, pct, ts: cur?.ts }
  }, [indicators])

  return (
    <div className="panel rounded-sm h-full" style={{ minHeight: '460px' }}>
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div className="section-header text-sm">
            <span style={{ color: '#00d4ff' }}>◆</span>
            個股日K查詢
            {activeSymbol && (
              <span className="mono text-sm font-bold" style={{ color: '#e8f1ff' }}>{activeSymbol}</span>
            )}
            {activeName && (
              <span style={{ color: '#8ba3c7', fontFamily: 'Noto Sans TC', fontSize: '0.92rem' }}>{activeName}</span>
            )}
          </div>

          {/* 個股代號輸入框 + datalist 自動完成 */}
          <div className="flex items-center gap-2">
            <input
              list="symbol-options"
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitQuery() }}
              placeholder="輸入代號 如 2330.TW"
              spellCheck={false}
              className="mono text-xs px-3 py-1 rounded-sm"
              style={{
                background: 'rgba(10,15,30,0.9)',
                border: '1px solid #1f3060',
                color: '#c8daf0',
                width: '170px',
                outline: 'none',
              }}
            />
            <datalist id="symbol-options">
              {symbolList.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.name ? `${s.name} · ${s.market || ''}` : s.market || ''}
                </option>
              ))}
            </datalist>
            <button
              onClick={submitQuery}
              className="mono text-xs px-3 py-1 rounded-sm transition-colors"
              style={{
                background: 'rgba(0,212,255,0.12)',
                border: '1px solid rgba(0,212,255,0.4)',
                color: '#00d4ff',
                cursor: 'pointer',
              }}
            >
              查詢
            </button>
          </div>
        </div>

        <div className="flex items-center justify-end mb-3 gap-4 flex-wrap">

          {/* Price summary：收盤(大) + 開盤 + 當日漲幅（紅漲綠跌） */}
          {dayInfo && (() => {
            const col = (dayInfo.chg ?? 0) >= 0 ? '#ff3366' : '#00ff88'
            return (
            <div className="flex items-end gap-5 mr-4">
              <div className="text-right">
                <div className="mono font-bold" style={{ color: col, fontSize: '1.9rem', lineHeight: 1 }}>{fmtPrice(dayInfo.close)}</div>
                <div className="mono text-xs mt-0.5" style={{ color: '#4a6080' }}>{dayInfo.ts?.slice(0, 10)} 收盤</div>
              </div>
              <div className="text-right" style={{ lineHeight: 1.5 }}>
                <div className="mono text-sm" style={{ color: '#8ba3c7' }}>
                  開 <span style={{ color: '#c8daf0' }}>{fmtPrice(dayInfo.open)}</span>
                </div>
                <div className="mono text-base font-bold" style={{ color: col }}>
                  {dayInfo.chg != null ? `${dayInfo.chg >= 0 ? '+' : ''}${fmtPrice(dayInfo.chg)}` : '—'}
                  {dayInfo.pct != null ? ` (${dayInfo.pct >= 0 ? '+' : ''}${dayInfo.pct.toFixed(2)}%)` : ''}
                </div>
              </div>
              {latestStrat && (
                <div className="text-right">
                  <div className="mono text-sm font-bold" style={{ color: RATING_COLORS[latestStrat.rating] || '#8ba3c7' }}>
                    {latestStrat.score ?? '—'}
                  </div>
                  <div className="mono text-xs" style={{ color: RATING_COLORS[latestStrat.rating] || '#4a6080' }}>
                    {(latestStrat.rating || '').toUpperCase()}
                  </div>
                </div>
              )}
            </div>
            )
          })()}

          {/* Controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowStrategy(v => !v)}
              className="mono text-xs px-3 py-1 rounded-sm transition-colors"
              style={{
                background: showStrategy ? 'rgba(0,212,255,0.1)' : 'rgba(26,37,64,0.5)',
                border: `1px solid ${showStrategy ? 'rgba(0,212,255,0.4)' : '#1a2540'}`,
                color: showStrategy ? '#00d4ff' : '#4a6080',
                cursor: 'pointer',
              }}
            >
              策略疊加
            </button>
          </div>
        </div>

        {/* MA 開關（點擊切換顯示／隱藏） */}
        <div className="flex gap-3 mb-3">
          {MA_CONFIG.map(m => {
            const on = maVisible[m.key]
            return (
              <button
                key={m.key}
                onClick={() => setMaVisible(v => ({ ...v, [m.key]: !v[m.key] }))}
                className="flex items-center gap-1 mono text-xs"
                style={{
                  cursor: 'pointer',
                  background: 'transparent',
                  border: 'none',
                  padding: 0,
                  opacity: on ? 1 : 0.35,
                }}
                title={on ? '點擊隱藏' : '點擊顯示'}
              >
                <div style={{ width: 16, height: 2, background: on ? m.color : '#4a6080', borderRadius: 1 }} />
                <span style={{ color: on ? m.color : '#4a6080', textDecoration: on ? 'none' : 'line-through' }}>{m.name}</span>
              </button>
            )
          })}
          {/* 布林通道開關 */}
          <button
            onClick={() => setShowBB(v => !v)}
            className="flex items-center gap-1 mono text-xs"
            style={{ cursor: 'pointer', background: 'transparent', border: 'none', padding: 0, opacity: showBB ? 1 : 0.35 }}
            title={showBB ? '點擊隱藏布林通道' : '點擊顯示布林通道'}
          >
            <div style={{ width: 16, height: 2, background: showBB ? BB_COLOR : '#4a6080', borderRadius: 1, borderTop: showBB ? `1px dashed ${BB_COLOR}` : 'none' }} />
            <span style={{ color: showBB ? BB_COLOR : '#4a6080', textDecoration: showBB ? 'none' : 'line-through' }}>布林(20,2)</span>
          </button>
          {latest && (
            <>
              <div className="ml-2 flex items-center gap-1">
                <div style={{ width: 8, height: 8, background: '#ff3366', borderRadius: 1 }} />
                <span className="mono text-xs" style={{ color: '#4a6080' }}>漲</span>
              </div>
              <div className="flex items-center gap-1">
                <div style={{ width: 8, height: 8, background: '#00ff88', borderRadius: 1 }} />
                <span className="mono text-xs" style={{ color: '#4a6080' }}>跌</span>
              </div>
            </>
          )}
          {/* 名詞說明（滑鼠移上顯示開/收/高/低定義） */}
          <span
            className="mono text-xs"
            style={{ color: '#4a6080', cursor: 'help', marginLeft: 'auto', borderBottom: '1px dotted #2a3a5a' }}
            title={
              '開盤價：開盤後，第一筆成交的價格\n' +
              '收盤價：收盤前，最後一筆成交的價格\n' +
              '最高價：一段期間內，成交的最高價\n' +
              '最低價：一段期間內，成交的最低價'
            }
          >
            ⓘ 開/收/高/低 說明
          </span>
        </div>

        {error && (
          <div className="mono text-xs mb-3 px-3 py-2 rounded" style={{ background: 'rgba(255,51,102,0.08)', border: '1px solid rgba(255,51,102,0.3)', color: '#ff3366' }}>
            ERR: {error}
          </div>
        )}

        {!activeSymbol ? (
          <div className="flex flex-col items-center justify-center" style={{ height: '360px' }}>
            <div className="mono text-2xl mb-2" style={{ color: '#1a2540' }}>◯</div>
            <div className="mono text-xs" style={{ color: '#2a3a5a' }}>輸入股票代號以載入日 K 線</div>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center" style={{ height: '360px' }}>
            <div className="mono text-sm" style={{ color: '#1f3060' }}>[ LOADING CHART... ]</div>
          </div>
        ) : !option ? (
          <div className="flex items-center justify-center" style={{ height: '360px' }}>
            <div className="mono text-sm" style={{ color: '#2a3a5a' }}>NO DATA</div>
          </div>
        ) : (
          <ReactECharts
            option={option}
            style={{ height: '400px', width: '100%' }}
            opts={{ renderer: 'canvas' }}
            notMerge={true}
            lazyUpdate={false}
          />
        )}
      </div>
    </div>
  )
}
