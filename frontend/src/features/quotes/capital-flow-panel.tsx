import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { AlertTriangle } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import type { EChartsCoreOption } from 'echarts'

interface FlowPoint {
  time: string
  in_flow?: number | null
  out_flow?: number | null
}

interface CapitalFlowResp {
  status: string
  source?: string
  flow?: FlowPoint[]
  period_type?: string
  message?: string
}

export function CapitalFlowPanel({ symbol }: { symbol: string }) {
  const api = apiClient
  const [flow, setFlow] = useState<FlowPoint[]>([])
  const [stale, setStale] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setStale(false)
    setFlow([])

    const load = async () => {
      try {
        const res = await api.get<{ data: CapitalFlowResp; status: number }>(
          `/market/capital-flow/${encodeURIComponent(symbol)}?period_type=INTRADAY`,
        )
        const body = res?.data
        if (cancelled) return
        if (body?.status === 'success' && body.flow?.length) {
          setFlow(body.flow)
          setStale(false)
        } else {
          setStale(true)
        }
      } catch {
        if (!cancelled) setStale(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    // 资金流向分时，60s 轮询足够
    const t = setInterval(load, 60000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [symbol, api])

  const containerRef = useEChart((): EChartsCoreOption | null => {
    if (!flow.length) return null
    const times = flow.map((p) =>
      (p.time || '').slice(-8).replace(/:/g, ':'),
    )
    const inFlow = flow.map((p) => (p.in_flow ?? 0) / 1e6)
    const outFlow = flow.map((p) => -(p.out_flow ?? 0) / 1e6)
    return {
      grid: { left: 44, right: 12, top: 16, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: ECHART_DARK.tooltipBg,
        textStyle: { color: ECHART_DARK.text, fontSize: 10 },
      },
      legend: {
        data: ['净流入', '净流出'],
        textStyle: { color: ECHART_DARK.text, fontSize: 9 },
        right: 8,
        top: 0,
      },
      xAxis: {
        type: 'category',
        data: times,
        axisLabel: { color: ECHART_DARK.text, fontSize: 8, interval: Math.ceil(times.length / 6) },
        axisLine: { lineStyle: { color: ECHART_DARK.split } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: ECHART_DARK.text, fontSize: 8, formatter: '{value}M' },
        splitLine: { lineStyle: { color: ECHART_DARK.split } },
      },
      series: [
        {
          name: '净流入',
          type: 'line',
          stack: 'flow',
          areaStyle: { color: 'rgba(16,185,129,0.25)' },
          lineStyle: { color: ECHART_DARK.up, width: 1 },
          itemStyle: { color: ECHART_DARK.up },
          data: inFlow,
          showSymbol: false,
        },
        {
          name: '净流出',
          type: 'line',
          stack: 'flow',
          areaStyle: { color: 'rgba(239,68,68,0.25)' },
          lineStyle: { color: ECHART_DARK.down, width: 1 },
          itemStyle: { color: ECHART_DARK.down },
          data: outFlow,
          showSymbol: false,
        },
      ],
    }
  }, [flow, stale])

  return (
    <div className={cn('glass-card rounded-lg overflow-hidden', stale && 'opacity-60 saturate-50')}>
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/20">
        <span className="text-[10px] font-semibold text-foreground/80">资金流向（净流入/流出）</span>
        {stale ? (
          <span className="text-[9px] text-amber-500 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> STALE
          </span>
        ) : (
          <span className="text-[9px] text-muted-foreground">Futu · 分时</span>
        )}
      </div>
      <div className="relative h-40">
        {loading && !flow.length ? (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-muted-foreground">
            加载资金流向…
          </div>
        ) : stale && !flow.length ? (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-amber-500">
            数据源暂不可用 · 资金流向未返回
          </div>
        ) : (
          <div ref={containerRef} className="w-full h-full" />
        )}
      </div>
    </div>
  )
}
