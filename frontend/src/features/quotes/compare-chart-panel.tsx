'use client'

import React, { useState } from 'react'
import { useMarketData } from '@/hooks/use-market-data'
import { LightweightChartCanvas } from '@/features/quotes/lightweight-chart-canvas'
import { AnomalyFlash } from '@/features/quotes/anomaly-flash'
import { NarratorBubble } from '@/features/quotes/narrator-bubble'

// PROD-12: 分屏对比子面板——拥有独立行情数据（独立 WebSocket/历史），并与主图共享同一 syncGroup 实现十字线同步
const COMPARE_PERIODS = [
  { id: '1m', label: '分时' }, { id: '5m', label: '5分' }, { id: '15m', label: '15分' },
  { id: '1h', label: '1时' }, { id: '4h', label: '4时' }, { id: '1d', label: '日K' },
  { id: '1w', label: '周K' }, { id: '1M', label: '月K' },
]

interface CompareChartPanelProps {
  watchlist: any[]
  updateTicker: (s: string, d: any) => void
  mainSymbol: string
  theme: string | undefined
  syncGroup: string
}

/** UIRF-14: 对比图表子面板（从 quotes.tsx 拆分） */
export function CompareChartPanel({ watchlist, updateTicker, mainSymbol, theme, syncGroup }: CompareChartPanelProps) {
  const [compareSymbol, setCompareSymbol] = useState<string>(() => {
    const others = watchlist.filter((w: any) => w.symbol !== mainSymbol)
    return others[0]?.symbol ?? mainSymbol
  })
  const [comparePeriod, setComparePeriod] = useState<string>('1d')
  const { realQuote, realHistory, gatewayStatus } = useMarketData({ selectedSymbol: compareSymbol, selectedPeriod: comparePeriod, watchlist, updateTicker })
  const selected = watchlist.find((w: any) => w.symbol === compareSymbol) ?? watchlist[0]

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-1 border-b border-border/40 bg-secondary/20 text-[10px] shrink-0">
        <span className="text-muted-foreground font-medium">对比标的</span>
        <select value={compareSymbol} onChange={(e) => setCompareSymbol(e.target.value)} className="bg-card border border-border/50 rounded px-1.5 py-0.5 text-[10px]">
          {watchlist.map((w: any) => <option key={w.symbol} value={w.symbol}>{w.symbol}</option>)}
        </select>
        <span className="text-muted-foreground font-medium ml-2">周期</span>
        <select value={comparePeriod} onChange={(e) => setComparePeriod(e.target.value)} className="bg-card border border-border/50 rounded px-1.5 py-0.5 text-[10px]">
          {COMPARE_PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <span className="text-muted-foreground/70 ml-auto">十字线已与主图同步</span>
      </div>
      <div className="flex-1 min-h-0">
        <AnomalyFlash symbol={compareSymbol} className="h-full">
          <LightweightChartCanvas selectedSymbol={compareSymbol} selectedPeriod={comparePeriod} setSelectedPeriod={setComparePeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={false} toggleWatchlist={() => {}} selectedItem={selected} hasData={watchlist.length > 0} syncGroup={syncGroup} />
          <NarratorBubble symbol={compareSymbol} />
        </AnomalyFlash>
      </div>
    </div>
  )
}
