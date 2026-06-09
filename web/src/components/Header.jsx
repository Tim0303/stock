import React from 'react'

export default function Header({ loading, lastRefresh, countdown, refreshTotal, onRefresh }) {
  const progress = countdown / refreshTotal
  const circumference = 2 * Math.PI * 8
  const dashOffset = circumference * (1 - progress)

  const timeStr = lastRefresh
    ? lastRefresh.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '--:--:--'

  return (
    <header className="relative border-b" style={{ borderColor: '#1f3060', background: 'rgba(10,15,30,0.95)', backdropFilter: 'blur(10px)' }}>
      {/* Top accent line */}
      <div className="absolute top-0 left-0 right-0 h-px" style={{ background: 'linear-gradient(90deg, transparent, #00d4ff, #00ff88, transparent)' }} />

      <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center justify-between">
        {/* Logo / Title */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {/* Hex icon */}
            <svg width="32" height="32" viewBox="0 0 32 32">
              <polygon
                points="16,2 29,9.5 29,22.5 16,30 3,22.5 3,9.5"
                fill="none"
                stroke="#00d4ff"
                strokeWidth="1.5"
              />
              <polygon
                points="16,7 24,11.5 24,20.5 16,25 8,20.5 8,11.5"
                fill="rgba(0,212,255,0.1)"
                stroke="#00d4ff"
                strokeWidth="0.5"
              />
              <text x="16" y="19" textAnchor="middle" fill="#00d4ff" fontSize="7" fontFamily="Rajdhani" fontWeight="700">AI</text>
            </svg>

            <div>
              <div className="font-display font-bold text-lg tracking-widest glow-cyan" style={{ color: '#00d4ff', fontFamily: 'Rajdhani' }}>
                WARROOM
              </div>
              <div className="text-xs tracking-widest" style={{ color: '#4a6080', fontFamily: 'Share Tech Mono' }}>
                智能 AI 選股平台
              </div>
            </div>
          </div>

          {/* Divider */}
          <div className="w-px h-8" style={{ background: '#1f3060' }} />

          {/* Status indicator */}
          <div className="flex items-center gap-2">
            <div className={`pulse-dot ${loading ? 'opacity-50' : ''}`} style={{ background: loading ? '#ffb800' : '#00ff88' }} />
            <span className="mono text-xs" style={{ color: loading ? '#ffb800' : '#00ff88' }}>
              {loading ? 'SYNCING' : 'LIVE'}
            </span>
          </div>
        </div>

        {/* Right side: time + countdown */}
        <div className="flex items-center gap-6">
          <div className="text-right hidden sm:block">
            <div className="mono text-xs" style={{ color: '#4a6080' }}>LAST SYNC</div>
            <div className="mono text-sm" style={{ color: '#8ba3c7' }}>{timeStr}</div>
          </div>

          {/* Countdown ring */}
          <button
            onClick={onRefresh}
            className="relative flex items-center justify-center w-10 h-10 rounded-full cursor-pointer transition-transform hover:scale-110"
            style={{ background: 'rgba(0,212,255,0.05)', border: '1px solid #1f3060' }}
            title={`下次刷新: ${countdown}s`}
          >
            <svg width="36" height="36" viewBox="0 0 36 36" style={{ position: 'absolute' }}>
              <circle cx="18" cy="18" r="14" fill="none" stroke="#1a2540" strokeWidth="2" />
              <circle
                cx="18" cy="18" r="14"
                fill="none"
                stroke="#00d4ff"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                style={{ transform: 'rotate(-90deg)', transformOrigin: '18px 18px', transition: 'stroke-dashoffset 1s linear' }}
              />
            </svg>
            <span className="mono text-xs relative z-10" style={{ color: '#00d4ff', fontSize: '0.6rem' }}>{countdown}</span>
          </button>

          {/* Market badge */}
          <div className="hidden md:flex items-center gap-2 px-3 py-1 rounded" style={{ background: 'rgba(0,212,255,0.06)', border: '1px solid rgba(0,212,255,0.2)' }}>
            <span className="mono text-xs" style={{ color: '#4a6080' }}>MKT</span>
            <span className="mono text-xs font-bold" style={{ color: '#00d4ff' }}>TW</span>
          </div>
        </div>
      </div>
    </header>
  )
}
