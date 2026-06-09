import React, { useState, useEffect, useCallback, useRef } from 'react'
import CandidatesPanel from './components/CandidatesPanel.jsx'
import AccuracyPanel from './components/AccuracyPanel.jsx'
import SkillsPanel from './components/SkillsPanel.jsx'
import ChartPanel from './components/ChartPanel.jsx'
import VcpWatchlistPanel from './components/VcpWatchlistPanel.jsx'
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
  const [vcpWatchlist, setVcpWatchlist] = useState([])
  const [vcpScanDate, setVcpScanDate] = useState(null)
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
      apiFetch('/api/vcp-watchlist'),
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
      setVcpWatchlist(results[3].value.data || [])
      setVcpScanDate(results[3].value.scan_date || null)
    } else {
      errs.vcpWatchlist = results[3].reason?.message
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
        {/* Top row: Candidates + Accuracy */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-4">
          <div className="xl:col-span-2 fade-in fade-in-delay-1">
            <CandidatesPanel
              data={candidates}
              loading={loading}
              error={errors.candidates}
              selectedSymbol={selectedSymbol}
              onSelect={setSelectedSymbol}
            />
          </div>
          <div className="fade-in fade-in-delay-2">
            <AccuracyPanel
              data={accuracy}
              loading={loading}
              error={errors.accuracy}
            />
          </div>
        </div>

        {/* Bottom row: Chart + Skills */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="xl:col-span-2 fade-in fade-in-delay-3">
            <ChartPanel symbol={selectedSymbol} />
          </div>
          <div className="fade-in fade-in-delay-4">
            <SkillsPanel
              data={skills}
              loading={loading}
              error={errors.skills}
            />
          </div>
        </div>

        {/* VCP 突破監控（第五分析師） */}
        <div className="grid grid-cols-1 gap-4 mt-4">
          <div className="fade-in fade-in-delay-4">
            <VcpWatchlistPanel
              data={vcpWatchlist}
              scanDate={vcpScanDate}
              loading={loading}
              error={errors.vcpWatchlist}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
