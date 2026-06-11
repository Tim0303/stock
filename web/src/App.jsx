import React, { useState, useEffect, useCallback, useRef } from 'react'
import CandidatesPanel from './components/CandidatesPanel.jsx'
import AccuracyPanel from './components/AccuracyPanel.jsx'
import SkillsPanel from './components/SkillsPanel.jsx'
import ChartPanel from './components/ChartPanel.jsx'
import AnalystPicksPanel from './components/AnalystPicksPanel.jsx'
import EodSignalsPanel from './components/EodSignalsPanel.jsx'
import Header from './components/Header.jsx'

const REFRESH_INTERVAL = 30 // seconds

async function apiFetch(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export default function App() {
  const [candidates, setCandidates] = useState([])
  const [accuracy, setAccuracy] = useState([])
  const [skills, setSkills] = useState([])
  const [analysts, setAnalysts] = useState([])
  const [analystsComputing, setAnalystsComputing] = useState(false)
  const [eodSignals, setEodSignals] = useState([])
  const [eodScanTime, setEodScanTime] = useState(null)
  const [market, setMarket] = useState(null)
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL)
  const [errors, setErrors] = useState({})
  const timerRef = useRef(null)
  const countdownRef = useRef(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    const errs = {}

    const results = await Promise.allSettled([
      apiFetch('/api/candidates?market=TW&limit=20'),
      apiFetch('/api/accuracy'),
      apiFetch('/api/skills'),
      apiFetch('/api/analyst-picks'),
      apiFetch('/api/eod-signals'),
    ])

    if (results[0].status === 'fulfilled') {
      const data = results[0].value.data || []
      setCandidates(data)
      if (data.length > 0 && !selectedSymbol) {
        setSelectedSymbol(data[0].symbol)
      }
    } else {
      errs.candidates = results[0].reason?.message
    }

    if (results[1].status === 'fulfilled') {
      setAccuracy(results[1].value.data || [])
    } else {
      errs.accuracy = results[1].reason?.message
    }

    if (results[2].status === 'fulfilled') {
      setSkills(results[2].value.data || [])
    } else {
      errs.skills = results[2].reason?.message
    }

    if (results[3].status === 'fulfilled') {
      const v = results[3].value
      const picks = v.analysts || []
      setAnalystsComputing(!!v.computing)
      if (v.market) setMarket(v.market)
      // 快照背景重算中（computing 且暫無資料）時保留現有畫面，避免資料瞬間「消失」
      if (!(v.computing && picks.length === 0)) {
        setAnalysts(picks)
      }
    } else {
      errs.analysts = results[3].reason?.message
    }

    if (results[4].status === 'fulfilled') {
      setEodSignals(results[4].value.data || [])
      setEodScanTime(results[4].value.scan_time || null)
    } else {
      errs.eod = results[4].reason?.message
    }

    setErrors(errs)
    setLastRefresh(new Date())
    setLoading(false)
    setCountdown(REFRESH_INTERVAL)
  }, [selectedSymbol])

  useEffect(() => {
    fetchAll()
  }, [])

  // Auto-refresh timer
  useEffect(() => {
    timerRef.current = setInterval(fetchAll, REFRESH_INTERVAL * 1000)
    return () => clearInterval(timerRef.current)
  }, [fetchAll])

  // Countdown tick
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      setCountdown(c => (c > 0 ? c - 1 : REFRESH_INTERVAL))
    }, 1000)
    return () => clearInterval(countdownRef.current)
  }, [])

  return (
    <div className="bg-grid min-h-screen" style={{ background: '#030712' }}>
      <Header
        loading={loading}
        lastRefresh={lastRefresh}
        countdown={countdown}
        refreshTotal={REFRESH_INTERVAL}
        onRefresh={fetchAll}
      />

      <main className="p-4 max-w-screen-2xl mx-auto">
        {/* 尾盤即時訊號（盤中 13:10 即時報價試算，預覽不記錄）— 時效優先置頂 */}
        <div className="mb-4 fade-in fade-in-delay-1">
          <EodSignalsPanel
            data={eodSignals}
            scanTime={eodScanTime}
            loading={loading}
            error={errors.eod}
            onSelect={setSelectedSymbol}
            selectedSymbol={selectedSymbol}
          />
        </div>

        {/* 需求1：5 位分析師推薦（各自列出，含 VCP 區塊） */}
        <div className="mb-4 fade-in fade-in-delay-1">
          <AnalystPicksPanel
            analysts={analysts}
            loading={loading}
            computing={analystsComputing}
            error={errors.analysts}
            onSelect={setSelectedSymbol}
            market={market}
          />
        </div>

        {/* 需求2：個股日K查詢（含代號輸入） + 今日候選榜 */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4">
          <div className="xl:col-span-2 fade-in fade-in-delay-2">
            <ChartPanel symbol={selectedSymbol} />
          </div>
          <div className="fade-in fade-in-delay-3">
            <CandidatesPanel
              data={candidates}
              loading={loading}
              error={errors.candidates}
              selectedSymbol={selectedSymbol}
              onSelect={setSelectedSymbol}
            />
          </div>
        </div>

        {/* 下方：三方準確率 + 技能績效 */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="fade-in fade-in-delay-4">
            <AccuracyPanel
              data={accuracy}
              loading={loading}
              error={errors.accuracy}
            />
          </div>
          <div className="fade-in fade-in-delay-4">
            <SkillsPanel
              data={skills}
              loading={loading}
              error={errors.skills}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
