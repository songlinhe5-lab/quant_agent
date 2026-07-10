'use client'

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineSeries } from 'lightweight-charts'

export function HighFreqChartWrapper({ symbol }: { symbol: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null)

  useEffect(() => {
    if (!chartContainerRef.current) return

    // 1. 初始化纯 Canvas 图表 (零 DOM 开销)
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255, 255, 255, 0.08)' }, horzLines: { color: 'rgba(255, 255, 255, 0.08)' } },
      timeScale: {
        borderColor: '#475569',
        timeVisible: true,
        fixLeftEdge: true,
        fixRightEdge: true,
        rightOffset: 0,
        barSpacing: 3,
        minBarSpacing: 3,
        maxBarSpacing: 3,
      },
    })

    const lineSeries = chart.addSeries(LineSeries, { color: '#10b981', lineWidth: 2 })
    lineSeriesRef.current = lineSeries

    // 2. 监听底层 WebSocket Event Bus
    const handleTick = (e: Event) => {
      const detail = (e as CustomEvent).detail
      // 💡 修复：标准化 ticker 格式进行匹配
      const cleanTicker = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
      if (cleanTicker(detail.ticker) === cleanTicker(symbol) && lineSeriesRef.current) {
        const lastPrice = parseFloat(detail.last_price)
        if (lastPrice > 0) {
          lineSeriesRef.current.update({
            time: Math.floor(Date.now() / 1000) as any,
            value: lastPrice
          })
        }
      }
    }

    window.addEventListener('market_tick', handleTick)

    return () => {
      window.removeEventListener('market_tick', handleTick)
      chart.remove()
    }
  }, [symbol])

  return (
    <div 
      ref={chartContainerRef} 
      className="w-full h-full min-h-[300px]"
      suppressHydrationWarning
    />
  )
}