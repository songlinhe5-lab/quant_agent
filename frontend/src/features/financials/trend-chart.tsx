'use client'

/**
 * FIN-07 · 多期趋势（docs/28 §七）：收入/利润/现金流 TTM 折线 + 净利率副轴。
 */

import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { ECHART_DARK, useEChart } from '@/hooks/use-echart'
import { FINANCIALS_PATHS, type AnalyticsView } from './api'
import { useFinancialsData } from './use-financials-data'

const SERIES = [
  { key: 'revenue', name: '收入 TTM', color: ECHART_DARK.accent },
  { key: 'net_income', name: '净利润 TTM', color: ECHART_DARK.up },
  { key: 'cfo', name: '经营现金流 TTM', color: ECHART_DARK.primary },
] as const

export function TrendChart({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<AnalyticsView>(FINANCIALS_PATHS.analytics(entity))

  const labels = data?.ttm.revenue.map((p) => p.label) ?? []
  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!data) return null
    const byKey = (key: 'revenue' | 'net_income' | 'cfo') => data.ttm[key].map((p) => p.value)
    const rev = byKey('revenue')
    const ni = byKey('net_income')
    const margin = rev.map((v, i) => (v && ni[i] !== undefined ? Number((((ni[i] ?? 0) / v) * 100).toFixed(2)) : null))
    return {
      backgroundColor: 'transparent',
      textStyle: { color: ECHART_DARK.text },
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: ECHART_DARK.text } },
      grid: { left: 60, right: 60, bottom: 30 },
      xAxis: { type: 'category', data: labels, axisLabel: { color: ECHART_DARK.text } },
      yAxis: [
        { type: 'value', axisLabel: { color: ECHART_DARK.text }, splitLine: { lineStyle: { color: ECHART_DARK.split } } },
        { type: 'value', axisLabel: { formatter: '{value}%', color: ECHART_DARK.text }, splitLine: { show: false } },
      ],
      series: [
        ...SERIES.map((s) => ({ name: s.name, type: 'line' as const, data: byKey(s.key), itemStyle: { color: s.color } })),
        { name: '净利率', type: 'line', yAxisIndex: 1, data: margin, itemStyle: { color: ECHART_DARK.warn }, lineStyle: { type: 'dashed' } },
      ],
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const chartRef = useEChart(() => option, [option])

  if (error) return <EmptyState title="趋势加载失败" description={error} />
  if (!data || labels.length === 0)
    return <EmptyState title={loading ? '加载中…' : '无 TTM 序列'} description="TTM 需要连续四个季度的拆季数据" />

  return (
    <div className="space-y-1">
      <div ref={chartRef} className="h-[340px] w-full" data-testid="trend-chart" />
      <p className="text-xs text-gray-500">最新年报 {data.latest_period} · TTM 为连续四季滚动合计</p>
    </div>
  )
}

export default TrendChart
