'use client'

// @ts-ignore
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
    })

    const lineSeries = chart.addSeries(LineSeries, { color: '#10b981', lineWidth: 2 })
    lineSeriesRef.current = lineSeries

    // 灌入回溯数据 (省略...)

    // 2. 监听底层 WebSocket Event Bus
    const handleTick = (e: Event) => {
      const { ticker, last_price } = (e as CustomEvent).detail
      if (ticker === symbol && lineSeriesRef.current) {
        // 🚨 直接调用图表底层 API 更新！
        // React 生命周期、useState、Profiler 完全不会被触发，抗住每秒万次推送！
        lineSeriesRef.current.update({
          time: Math.floor(Date.now() / 1000) as any,
          value: parseFloat(last_price)
        })
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
      suppressHydrationWarning // 防止 Next.js/React SSR 抖动干预
    />
  )
}