import React, { useState, useEffect, useMemo, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'

async function fetchIndicators(symbol, limit = 120) {
  const res = await fetch(`/api/indicators/${encodeURIComponent(symbol)}?limit=${limit}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchStrategy(symbol, limit = 120) {
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

function buildChartOption(indicators, strategy, showStrategy) {
  if (!indicators || indicators.length === 0) return null

  // Sort chronologically
  const sorted = [...indicators].sort((a, b) => new Date(a.ts) - new Date(b.ts))
  const stratMap = {}
  if (strategy) {
    strategy.forEach(s => { stratMap[s.ts] = s })
  }

  const dates = sorted.map(d => d.ts.slice(0, 10))
  const candleData = sorted.map(d => [d.open, d.close, d.low, d.high])
  const volumes = sorted.map(d => d.volume)
  const ma5 = sorted.map(d => d.ma5 != null ? +d.ma5.toFixed(2) : null)
  const ma10 = sorted.map(d => d.ma10 != null ? +d.ma10.toFixed(2) : null)
  const ma20 = sorted.map(d => d.ma20 != null ? +d.ma20.toFixed(2) : null)

  // Strategy signal markers
  const markPoints = []
  if (showStrategy && strategy) {
    sorted.forEach((d, i) => {
      const s = stratMap[d.ts]
      if (s && s.signal_type) {
        markPoints.push({
          coord: [i, d.high * 1.015],
          value: s.signal_type,
          itemStyle: { color: RATING_COLORS[s.rating] || '#00d4ff' },
        })
      }
    })
  }

  // Volume colors
  const volColors = sorted.map(d => d.close >= (d.open || d.close) ? 'rgba(0,255,136,0.6)' : 'rgba(255,51,102,0.6)')

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
      backgroundColor: 'rgba(10,15,30,0.95)',
      borderColor: '#1f3060',
      textStyle: { color: '#c8daf0', fontFamily: 'Share Tech Mono', fontSize: 11 },
      formatter(params) {
        if (!params || params.length === 0) return ''
        const date = params[0].axisValue
        let html = `<div style="color:#4a6080;margin-bottom:4px">${date}</div>`
        params.forEach(p => {
          if (p.seriesName === 'K線' && Array.isArray(p.value)) {
            const [o, c, l, h] = p.value
            const chg = c - o
            const pct = ((chg / o) * 100).toFixed(2)
            const color = c >= o ? '#00ff88' : '#ff3366'
            html += `<div style="color:${color}">O:${o} H:${h} L:${l} C:${c}</div>`
            html += `<div style="color:${color}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)} (${pct}%)</div>`
          } else if (p.seriesName && p.seriesName.startsWith('MA')) {
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
        axisLine: { show: false },
        axisLabel: {
          color: '#4a6080',
          fontFamily: 'Share Tech Mono',
          fontSize: 10,
          formatter: v => v.toFixed(1),
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
        start: Math.max(0, 100 - (60 / sorted.length) * 100),
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
        start: Math.max(0, 100 - (60 / sorted.length) * 100),
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
        itemStyle: {
          color: '#00ff88',
          color0: '#ff3366',
          borderColor: '#00cc66',
          borderColor0: '#cc2244',
          borderWidth: 1,
        },
        markPoint: markPoints.length > 0 ? {
          symbol: 'triangle',
          symbolSize: 10,
          data: markPoints,
          label: {
            show: true,
            formatter: p => p.value,
            color: '#fff',
            fontSize: 9,
            fontFamily: 'Share Tech Mono',
          },
        } : undefined,
      },
      {
        name: 'MA5',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma5,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#00d4ff', width: 1.5 },
        z: 5,
      },
      {
        name: 'MA10',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma10,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#b38fd4', width: 1.5 },
        z: 5,
      },
      {
        name: 'MA20',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma20,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#ffb800', width: 1.5 },
        z: 5,
      },
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
    legend: {
      top: 4,
      right: 16,
      textStyle: { color: '#4a6080', fontFamily: 'Share Tech Mono', fontSize: 10 },
      inactiveColor: '#2a3a5a',
      itemWidth: 16,
      itemHeight: 2,
      data: ['MA5', 'MA10', 'MA20'],
    },
  }
}

export default function ChartPanel({ symbol, defaultSymbol = '2330.TW' }) {
  const [indicators, setIndicators] = useState([])
  const [strategy, setStrategy] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showStrategy, setShowStrategy] = useState(true)

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
        fetchIndicators(sym, 120),
        fetchStrategy(sym, 120),
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
    () => buildChartOption(indicators, strategy, showStrategy),
    [indicators, strategy, showStrategy]
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

  return (
    <div className="panel rounded-sm" style={{ minHeight: '460px' }}>
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div className="section-header text-sm">
            <span style={{ color: '#00d4ff' }}>◆</span>
            個股日K查詢
            {activeSymbol && (
              <span className="mono text-sm font-bold" style={{ color: '#e8f1ff' }}>{activeSymbol}</span>
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

          {/* Price summary */}
          {latest && (
            <div className="flex items-center gap-4 mr-4">
              <div className="text-right">
                <div className="mono text-xl font-bold" style={{ color: '#e8f1ff' }}>{latest.close}</div>
                <div className="mono text-xs" style={{ color: '#4a6080' }}>{latest.ts?.slice(0, 10)}</div>
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
          )}

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

        {/* MA Legend quick labels */}
        <div className="flex gap-3 mb-3">
          {[
            { name: 'MA5', color: '#00d4ff' },
            { name: 'MA10', color: '#b38fd4' },
            { name: 'MA20', color: '#ffb800' },
          ].map(m => (
            <div key={m.name} className="flex items-center gap-1">
              <div style={{ width: 16, height: 2, background: m.color, borderRadius: 1 }} />
              <span className="mono text-xs" style={{ color: m.color }}>{m.name}</span>
            </div>
          ))}
          {latest && (
            <>
              <div className="ml-2 flex items-center gap-1">
                <div style={{ width: 8, height: 8, background: '#00ff88', borderRadius: 1 }} />
                <span className="mono text-xs" style={{ color: '#4a6080' }}>漲</span>
              </div>
              <div className="flex items-center gap-1">
                <div style={{ width: 8, height: 8, background: '#ff3366', borderRadius: 1 }} />
                <span className="mono text-xs" style={{ color: '#4a6080' }}>跌</span>
              </div>
            </>
          )}
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
