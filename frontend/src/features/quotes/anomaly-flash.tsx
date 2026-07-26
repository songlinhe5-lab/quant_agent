'use client'

import React, { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'

const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')

interface AnomalyFlashProps {
  symbol: string
  threshold?: number
  className?: string
  children: React.ReactNode
}

/**
 * PROD-04a: 盘口异动 > 2% 高对比闪烁动画。
 * 监听实时 market_tick / quote_update 的 change_pct，超过阈值时叠加基于 --scene-accent 的脉冲光环。
 * 受 useAiPushPrefStore 的 ai01 主开关控制（AI-09 底座）。
 */
export function AnomalyFlash({ symbol, threshold = 2, className, children }: AnomalyFlashProps) {
  const ai01Enabled = useAiPushPrefStore((s) => s.isEnabled('ai01'))
  const [active, setActive] = useState(false)
  const [dir, setDir] = useState<'up' | 'down'>('up')

  useEffect(() => {
    if (!ai01Enabled) {
      setActive(false)
      return
    }
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (!d?.ticker || cleanSym(String(d.ticker)) !== cleanSym(symbol)) return
      const raw = String(d.change_pct ?? '0').replace('%', '')
      const pct = parseFloat(raw) || 0
      const isUp = pct >= 0
      const over = Math.abs(pct) > threshold
      if (over) {
        setDir(isUp ? 'up' : 'down')
        setActive(true)
      } else {
        setActive(false)
      }
    }
    window.addEventListener('market_tick', handler)
    window.addEventListener('quote_update', handler)
    return () => {
      window.removeEventListener('market_tick', handler)
      window.removeEventListener('quote_update', handler)
    }
  }, [symbol, threshold, ai01Enabled])

  return (
    <div
      className={cn(
        'relative rounded-xl transition-shadow duration-300',
        active && 'scene-anomaly-flash',
        active && dir === 'up' && 'scene-anomaly-up',
        active && dir === 'down' && 'scene-anomaly-down',
        className
      )}
    >
      {active && (
        <span
          className="pointer-events-none absolute -top-2 left-1/2 -translate-x-1/2 z-20 px-2 py-0.5 rounded-full text-[9px] font-bold font-mono uppercase tracking-wider text-background"
          style={{ background: 'hsl(var(--scene-accent))' }}
        >
          {dir === 'up' ? '▲ 异动拉升' : '▼ 异动下杀'}
        </span>
      )}
      {children}
    </div>
  )
}
