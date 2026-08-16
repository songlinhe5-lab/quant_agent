import { useEffect, useState } from 'react'
import type { EChartsCoreOption } from 'echarts'
import { apiClient } from '@/lib/api-client'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface PayoffPoint {
  price: number
  pnl: number
}

interface StrategyLabData {
  ticker?: string
  strategy_type?: string
  available?: boolean
  break_even?: number[] | number
  max_profit?: number
  max_loss?: number
  payoff_curve?: PayoffPoint[]
  greeks_exposure?: Record<string, number>
  notes?: string[]
  source?: string
}

export function OptionStrategyLabPanel({ ticker = 'US.AAPL', strategyType = 'STRANGLE', spread = 5 }: { ticker?: string; strategyType?: string; spread?: number }) {
  const [data, setData] = useState<StrategyLabData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: StrategyLabData }>(`/market/option-strategy-lab?ticker=${encodeURIComponent(ticker)}&strategy_type=${strategyType}&spread=${spread}`)
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker, strategyType, spread])

  const buildOption = (): EChartsCoreOption | null => {
    const curve = data?.payoff_curve
    if (!curve || !curve.length) return null
    const xs = curve.map((p) => p.price)
    const ys = curve.map((p) => Number(p.pnl.toFixed(2)))
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: ECHART_DARK.tooltipBg,
        borderColor: ECHART_DARK.split,
        textStyle: { color: '#e2e8f0' },
        formatter: (params: any) => {
          const p = Array.isArray(params) ? params[0] : params
          return `标的价格: ${p.axisValue}<br/>损益: ${p.data >= 0 ? '+' : ''}${p.data}`
        },
      },
      grid: { left: 52, right: 16, top: 24, bottom: 32 },
      xAxis: {
        type: 'category',
        data: xs.map(String),
        axisLine: { lineStyle: { color: ECHART_DARK.split } },
        axisLabel: { color: ECHART_DARK.text, fontSize: 9, interval: Math.floor(xs.length / 6) },
      },
      yAxis: {
        type: 'value',
        name: '损益',
        nameTextStyle: { color: ECHART_DARK.text },
        axisLabel: { color: ECHART_DARK.text },
        splitLine: { lineStyle: { color: ECHART_DARK.split } },
      },
      series: [
        {
          type: 'line',
          data: ys,
          showSymbol: false,
          lineStyle: { color: ECHART_DARK.primary, width: 2 },
          itemStyle: { color: ECHART_DARK.primary },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: ECHART_DARK.split, type: 'dashed' },
            data: [{ yAxis: 0 }],
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(139,92,246,0.25)' },
                { offset: 1, color: 'rgba(139,92,246,0.02)' },
              ],
            },
          },
        },
      ],
    } as EChartsCoreOption
  }

  const ref = useEChart(buildOption, [data])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载期权损益实验室 ({ticker})…</div>
  if (error) return <div className="p-6 text-sm text-red-400">损益实验室数据获取失败：{error}</div>
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无期权损益数据</div>
  if (data.available === false) return <div className="p-6 text-sm text-slate-400">该标的暂无可组合的期权 legs（{data.notes?.join('；') || '数据不足'}）</div>

  const be = Array.isArray(data.break_even) ? data.break_even : data.break_even != null ? [data.break_even] : []
  const maxProfit = data.max_profit
  const maxLoss = data.max_loss

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">期权损益实验室</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker}</span>
        <span className="text-[10px] text-[#8b5cf6] font-mono">{data.strategy_type}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">盈亏平衡</div>
          <div className="text-sm font-semibold font-mono text-foreground/90">{be.length ? be.map((v) => v.toFixed(2)).join(' / ') : '--'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">最大盈利</div>
          <div className="text-sm font-semibold font-mono text-[#0ecb81]">{maxProfit != null ? (maxProfit >= 0 ? '+' : '') + maxProfit.toFixed(2) : '∞'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">最大亏损</div>
          <div className="text-sm font-semibold font-mono text-[#f6465d]">{maxLoss != null ? (maxLoss >= 0 ? '+' : '') + maxLoss.toFixed(2) : '∞'}</div>
        </div>
      </div>
      <div ref={ref} className="h-[280px] w-full px-2 pb-2" />
      {data.notes && data.notes.length > 0 && (
        <div className="px-3 pb-2 text-[9px] text-slate-500">{data.notes.join('；')}</div>
      )}
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 期权组合 legs 代数推导'} · 损益为组合 legs 代数求和，非 Black-Scholes 近似
      </div>
    </div>
  )
}
