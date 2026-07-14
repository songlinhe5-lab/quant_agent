/**
 * PT-02b: 净值曲线图 (Lightweight Charts)
 */
'use client'

import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi, LineStyle, AreaSeries } from 'lightweight-charts'
import { apiClient } from '@/lib/api-client'

interface NavPoint {
  trade_date: string
  nav: number
  cash: number
  market_value: number
  stale_symbols: { symbols: string[] } | null
}

interface NavChartProps {
  portfolioId: string
}

export function NavChart({ portfolioId }: NavChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<IChartApi | null>(null)
  const [data, setData] = useState<NavPoint[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiClient
      .get<any>(`/paper/portfolios/${portfolioId}/nav`, { days: 90 })
      .then((res) => setData(res.data?.data || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [portfolioId])

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return

    const chart = createChart(chartRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'currentColor',
      },
      width: chartRef.current.clientWidth,
      height: 300,
      timeScale: { timeVisible: false },
    })
    chartInstance.current = chart

    const series = chart.addSeries(AreaSeries, {
      lineColor: '#22c55e',
      topColor: 'rgba(34, 197, 94, 0.2)',
      bottomColor: 'rgba(34, 197, 94, 0.02)',
      lineWidth: 2,
    })

    const chartData = data.map((d) => ({
      time: d.trade_date as any,
      value: d.nav,
    }))
    series.setData(chartData)

    // STALE 标记
    const staleMarkers: any[] = []
    data.forEach((d) => {
      if (d.stale_symbols?.symbols?.length) {
        staleMarkers.push({
          time: d.trade_date as any,
          position: 'aboveBar' as const,
          color: '#f59e0b',
          shape: 'square' as const,
          text: 'STALE',
        })
      }
    })
    if (staleMarkers.length > 0) {
      ;(series as any).setMarkers(staleMarkers)
    }

    chart.timeScale().fitContent()

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [data])

  if (loading) {
    return <div className="h-[300px] flex items-center justify-center text-muted-foreground text-sm">加载中...</div>
  }

  if (data.length === 0) {
    return <div className="h-[300px] flex items-center justify-center text-muted-foreground text-sm">暂无净值数据</div>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">净值曲线</h3>
        <span className="text-xs text-muted-foreground font-mono">
          最新 NAV: {data[data.length - 1]?.nav.toFixed(2)}
        </span>
      </div>
      <div ref={chartRef} className="w-full" />
    </div>
  )
}
