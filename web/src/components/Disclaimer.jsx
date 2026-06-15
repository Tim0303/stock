import React from 'react'

// 法規定位：資訊/教育工具，非投資建議。各註冊/帳戶/Landing 共用。
export default function Disclaimer({ compact = false }) {
  return (
    <div className="mono" style={{
      fontSize: compact ? '0.62rem' : '0.7rem', lineHeight: 1.7, color: '#5a6a85',
      background: 'rgba(255,184,0,0.05)', border: '1px solid rgba(255,184,0,0.18)',
      borderRadius: 6, padding: compact ? '8px 10px' : '12px 14px',
    }}>
      <span style={{ color: '#ffb800' }}>⚠ 免責聲明</span>　本平台為
      <b style={{ color: '#8ba3c7' }}>資訊與教育工具</b>，提供技術分析訊號、回測與統計資訊，
      <b style={{ color: '#8ba3c7' }}>非投資建議、非買賣個股之推薦</b>。所有內容含模型誤差與生存者偏差，
      過去績效不代表未來表現。投資決策與風險請自行評估與承擔。
    </div>
  )
}
