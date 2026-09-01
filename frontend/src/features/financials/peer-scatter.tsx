'use client'

/**
 * FIN-09 · 同业截面散点（docs/28 §七）：peer_rows 明细行 + p25/p75 参考线。
 * FIN-06/07 曾因后端只回聚合而降级为区间条，本组件补齐散点视图（本体高亮）。
 */

import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts'

import { ECHART_DARK, useEChart } from '@/hooks/use-echart'
import type { PeersResponse } from './api'

export function PeerScatter({ data }: { data: PeersResponse }) {
  const option = useMemo<EChartsCoreOption | null>(() => {
    const rows = data.peer_rows ?? []
    if (!rows.length) return null
    const isSelf = (eid: string) => eid === data.entity_id
    return {
      backgroundColor: 'transparent',
      textStyle: { color: ECHART_DARK.text },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: [number, number]; name: string }) =>
          `${p.name}<br/>${(p.data[1] as number).toLocaleString()}`,
      },
      grid: { left: 70, right: 20, top: 20, bottom: 28 },
      xAxis: { type: 'value', show: false, min: 0, max: rows.length - 1 },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: ECHART_DARK.text, formatter: (v: number) => v.toLocaleString() },
        splitLine: { lineStyle: { color: ECHART_DARK.split } },
      },
      series: [
        {
          type: 'scatter',
          data: rows.map((r, i) => ({
            value: [i, r.value] as [number, number],
            name: r.entity_id,
            itemStyle: {
              color: isSelf(r.entity_id) ? ECHART_DARK.primary : ECHART_DARK.accent,
              opacity: isSelf(r.entity_id) ? 1 : 0.55,
              symbolSize: isSelf(r.entity_id) ? 14 : 6,
            },
          })),
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: ECHART_DARK.warn, type: 'dashed' },
            label: { color: ECHART_DARK.warn, formatter: '{b}' },
            data: [
              { name: 'p25', yAxis: data.aggregates.p25 },
              { name: 'median', yAxis: data.aggregates.median },
              { name: 'p75', yAxis: data.aggregates.p75 },
            ],
          },
        },
      ],
    }
  }, [data])

  const chartRef = useEChart(() => option, [option])

  if (!option) return null  // 无明细行时由调用方退回区间条
  return <div ref={chartRef} className="h-64 w-full" data-testid="peer-scatter" />
}

export default PeerScatter
