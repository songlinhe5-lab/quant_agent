'use client'

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineSeries } from 'lightweight-charts'

export function HighFreqChartWrapper({ symbol }: { symbol: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null)
  const hasSetRangeRef = useRef(false)

  useEffect(() => {
    if (!chartContainerRef.current) return

    // 💡 计算全天交易时间范围（9:30 开盘 - 16:00 收盘）
    const now = new Date()
    const todayStart = new Date(now)
    todayStart.setHours(9, 30, 0, 0)
    const todayEnd = new Date(now)
    todayEnd.setHours(16, 0, 0, 0)

    // 1. 初始化纯 Canvas 图表 (零 DOM 开销)
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255, 255, 255, 0.08)' }, horzLines: { color: 'rgba(255, 255, 255, 0.08)' } },
      timeScale: {
        borderColor: '#475569',
        timeVisible: true,
        fixLeftEdge: true,
        fixRightEdge: false,  // 💡 不固定右边界，允许右侧空白展示未交易时间
        rightOffset: 10,      // 💡 右侧留空
        barSpacing: 3,
        minBarSpacing: 3,
        maxBarSpacing: 3,
      },
    })
    chartRef.current = chart

    const lineSeries = chart.addSeries(LineSeries, { color: '#10b981', lineWidth: 2 })
    lineSeriesRef.current = lineSeries
    hasSetRangeRef.current = false

    // 💡 注意：此处不能立即调用 setVisibleRange —— series 尚无任何数据点，
    //    lightweight-charts 无法建立“时间→坐标”映射，会抛出 "Value is null"。
    //    改为在首个真实 tick 到达（series 有数据锚点）后再设置一次全天范围。

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
          // 💡 首个数据点到达后设置全天可见范围（此时时间轴已有锚点，不会 null）
          if (!hasSetRangeRef.current && chartRef.current) {
            hasSetRangeRef.current = true
            try {
              chartRef.current.timeScale().setVisibleRange({
                from: (todayStart.getTime() / 1000) as any,
                to: (todayEnd.getTime() / 1000) as any,
              })
            } catch {
              // 数据不足以映射到目标范围时静默忽略，交由图表自动缩放
            }
          }
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