'use client'

/**
 * FIN-07 · DuPont 分解面板（docs/28 §七）：逐财年 ROE 柱 + 三/五因子线。
 * 因子口径见后端 analytics.dupont_series（权益固定期末基数）。
 */

import { useMemo, useState } from 'react'
import type { EChartsCoreOption } from 'echarts'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { ECHART_DARK, useEChart } from '@/hooks/use-echart'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type AnalyticsView } from './api'
import { useFinancialsData } from './use-financials-data'

const F3 = ['net_margin', 'asset_turnover', 'equity_multiplier'] as const
const F5 = [...F3, 'tax_burden', 'interest_burden', 'operating_margin'] as const
const FACTOR_LABEL: Record<string, string> = {
  net_margin: '净利率',
  asset_turnover: '资产周转率',
  equity_multiplier: '权益乘数',
  tax_burden: '税负',
  interest_burden: '利息负担',
  operating_margin: '营业利润率',
}

export function DupontPanel({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<AnalyticsView>(FINANCIALS_PATHS.analytics(entity))
  const [five, setFive] = useState(false)
  const factors = five ? F5 : F3

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!data || data.dupont.length === 0) return null
    const periods = data.dupont.map((d) => d.period)
    const pct = (v: number | null) => (v === null ? null : Number((v * 100).toFixed(2)))
    return {
      backgroundColor: 'transparent',
      textStyle: { color: ECHART_DARK.text },
      tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}%` },
      legend: { textStyle: { color: ECHART_DARK.text } },
      grid: { left: 60, bottom: 30 },
      xAxis: { type: 'category', data: periods, axisLabel: { color: ECHART_DARK.text } },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: ECHART_DARK.text }, splitLine: { lineStyle: { color: ECHART_DARK.split } } },
      series: [
        {
          name: 'ROE（直算）',
          type: 'bar',
          data: data.dupont.map((d) => pct(d.roe)),
          itemStyle: { color: ECHART_DARK.primary },
        },
        ...factors.map((f, i) => ({
          name: FACTOR_LABEL[f],
          type: 'line' as const,
          data: data.dupont.map((d) => pct(d.factors_5[f] ?? d.factors[f as keyof typeof d.factors])),
          itemStyle: { color: [ECHART_DARK.up, ECHART_DARK.accent, ECHART_DARK.warn, ECHART_DARK.down, ECHART_DARK.text, '#a78bfa'][i % 6] },
        })),
      ],
    }
  }, [data, factors])

  const chartRef = useEChart(() => option, [option])

  if (error) return <EmptyState title="DuPont 加载失败" description={error} />
  if (!data || data.dupont.length === 0)
    return <EmptyState title={loading ? '加载中…' : '无 DuPont 序列'} description="DuPont 仅对年报（FY）出数，需至少两期年报" />

  const latest = data.dupont[data.dupont.length - 1]
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-xs">
        <button
          type="button"
          data-testid="dupont-toggle"
          onClick={() => setFive((v) => !v)}
          className={cn('rounded border px-2 py-1', five ? 'border-violet-500/40 text-violet-300' : 'border-gray-700 text-gray-400')}
        >
          {five ? '五因子' : '三因子'}
        </button>
        <span className="text-gray-500">
          {latest.period} ROE {latest.roe === null ? '--' : `${(latest.roe * 100).toFixed(1)}%`} · 权益基数 {latest.equity_base === 'ending' ? '期末' : '均值'}
          {latest.check_failed && <span className="text-red-400"> · 链式乘积校验失败</span>}
        </span>
      </div>
      <div ref={chartRef} className="h-[340px] w-full" data-testid="dupont-chart" />
    </div>
  )
}

export default DupontPanel
