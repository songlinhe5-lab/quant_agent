'use client'

import React, { useMemo } from 'react'
import { X } from 'lucide-react'
import { riskLevelOf } from '@/features/trading/risk-types'
import type { RiskRadarData } from '@/features/trading/risk-types'

/** UIRF-17: 风控帮助面板（从 risk-account-section 拆分） */
export function HelpPanel({ items, onClose, title }: { items: { name: string; desc: string }[]; onClose: () => void; title: string }) {
  return (
    <div className="px-3 py-2.5 bg-card/80 backdrop-blur-sm border-b border-border/30 space-y-1.5 animate-in fade-in slide-in-from-top-1 duration-200">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-foreground">{title}</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors"><X className="h-3 w-3" /></button>
      </div>
      {items.map(item => (
        <div key={item.name} className="flex items-start gap-2 text-[9px]">
          <span className="font-mono font-bold text-primary min-w-[60px] shrink-0">{item.name}</span>
          <span className="text-muted-foreground leading-relaxed">{item.desc}</span>
        </div>
      ))}
    </div>
  )
}

/** UIRF-17: 风险评分仪表盘（从 risk-account-section 拆分） */
export function RiskScoreGauge({ radar, isDark }: { radar: RiskRadarData[]; isDark: boolean }) {
  const score = useMemo(() => {
    if (!radar.length) return 0
    const avg = radar.reduce((s, d) => s + d.current, 0) / radar.length
    return Math.round(avg)
  }, [radar])

  const level = riskLevelOf(score)
  const color = level.color
  const label = level.label
  const circumference = 2 * Math.PI * 36
  const dash = (score / 100) * circumference

  return (
    <div className="flex flex-col items-center justify-center py-1">
      <div className="relative w-14 h-14">
        <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
          <circle cx="40" cy="40" r="36" fill="none" stroke={isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'} strokeWidth="7" />
          <circle cx="40" cy="40" r="36" fill="none" stroke={color} strokeWidth="7"
            strokeDasharray={`${dash} ${circumference - dash}`} strokeLinecap="round"
            className="transition-all duration-700 ease-out" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-sm font-bold font-mono tabular-nums" style={{ color }}>{score}</span>
          <span className="text-[7px] text-muted-foreground">/100</span>
        </div>
      </div>
      <span className="text-[8px] font-semibold mt-0.5" style={{ color }}>{label}</span>
    </div>
  )
}
