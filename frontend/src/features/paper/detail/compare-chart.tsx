/**
 * PT-02b: 对比叠加图 (纸面 vs 回测基准)
 */
'use client'

import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, IChartApi, LineStyle, LineSeries } from 'lightweight-charts'
import { apiClient } from '@/lib/api-client'

interface ChartPoint {
  idx: number
  paper: number | null
  benchmark: number | null
}

interface CompareData {
  tracking_error: number
  cumulative_drift: number
  chart: ChartPoint[]
  paper_sharpe: number
  paper_max_dd: number
}

interface CompareChartProps {
  portfolioId: string
}

export function CompareChart({ portfolioId }: CompareChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const [compareData, setCompareData] = useState<CompareData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiClient
      .get<any>(`/paper/portfolios/${portfolioId}/compare`, { days: 90 })
      .then((res) => setCompareData(res.data?.data || null))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [portfolioId])

  useEffect(() => {
    if (!chartRef.current || !compareData?.chart?.length) return

    const chart = createChart(chartRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'currentColor',
      },
      width: chartRef.current.clientWidth,
      height: 300,
      timeScale: { timeVisible: false },
    })

    // 纸面（绿实线）
    const paperSeries = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineWidth: 2,
      title: '纸面',
    })

    // 基准（紫虚线）
    const benchSeries = chart.addSeries(LineSeries, {
      color: '#a855f7',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      title: '基准',
    })

    const paperData = compareData.chart
      .filter((p) => p.paper !== null)
      .map((p, i) => ({ time: i as any, value: p.paper! }))

    const benchData = compareData.chart
      .filter((p) => p.benchmark !== null)
      .map((p, i) => ({ time: i as any, value: p.benchmark! }))

    paperSeries.setData(paperData)
    benchSeries.setData(benchData)
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
  }, [compareData])

  if (loading) {
    return <div className="h-[300px] flex items-center justify-center text-muted-foreground text-sm">加载中...</div>
  }

  if (!compareData) {
    return <div className="h-[300px] flex items-center justify-center text-muted-foreground text-sm">暂无对比数据</div>
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">纸面 vs 基准</h3>
        <div className="flex gap-4 text-xs font-mono">
          <span className="text-green-500">Sharpe: {compareData.paper_sharpe.toFixed(2)}</span>
          <span className="text-purple-500">TE: {(compareData.tracking_error * 100).toFixed(1)}%</span>
          <span>偏离: {(compareData.cumulative_drift * 100).toFixed(1)}pp</span>
        </div>
      </div>
      <div ref={chartRef} className="w-full" />
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-green-500 inline-block" /> 纸面组合
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-purple-500 inline-block border-dashed" /> 回测基准
        </span>
      </div>
    </div>
  )
}
