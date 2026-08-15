'use client'

import { useState, useEffect, useCallback } from 'react'
import { Coins, RefreshCw } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { EChartsRenderer } from '@/features/copilot/echarts-renderer'

// ─── 类型 ─────────────────────────────────────────────
interface Bucket {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
}
interface TokenUsageResponse {
  today: Bucket & { date: string; metric_source?: string }
  hourly: Array<Bucket & { date: string; hour: number }>
  monthly: Bucket & { month: string; metric_source?: string }
  daily_range: Array<Bucket & { date: string }>
  meta: { day: string; month: string; range_start: string; range_end: string; metric_source?: string }
}

type ViewMode = 'daily' | 'hourly' | 'monthly'

const fmt = (n: number) => n.toLocaleString('en-US')

// ─── 主组件 ──────────────────────────────────────────
export function TokenUsagePanel() {
  const [data, setData] = useState<TokenUsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [view, setView] = useState<ViewMode>('daily')
  const [days, setDays] = useState(7)

  const fetchData = useCallback(async () => {
    try {
      const res = await apiClient.get('/system/token-usage', { days }) as any
      if (res?.data) setData(res.data as TokenUsageResponse)
    } catch (e) {
      console.error('Token usage fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchData()
    setTimeout(() => setIsRefreshing(false), 500)
  }

  // KPI：今日 / 本月 / 近N日
  const todayTotal = data?.today?.total_tokens ?? 0
  const monthTotal = data?.monthly?.total_tokens ?? 0
  const rangeTotal = (data?.daily_range ?? []).reduce((s, d) => s + d.total_tokens, 0)

  const chartOptions = buildChartOptions(view, data)

  return (
    <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm relative flex flex-col">
      {/* 标题 */}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between bg-secondary/30 shrink-0">
        <div className="flex items-center gap-2">
          <Coins className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            LLM Token 消耗统计
          </span>
          <span className="text-[10px] font-mono text-muted-foreground/70 border border-border/50 rounded px-1.5 py-0.5">
            {data?.meta?.metric_source ?? '—'}
          </span>
        </div>
        <Button
          variant="outline" size="sm"
          onClick={handleRefresh} disabled={isRefreshing}
          className="h-7 px-3 gap-1.5 text-[11px] bg-secondary/30 hover:bg-secondary/60 border-border/50"
        >
          <RefreshCw className={cn('h-3 w-3', isRefreshing && 'animate-spin')} />
          {isRefreshing ? '同步中' : '刷新'}
        </Button>
      </div>

      {/* KPI 卡片 */}
      <div className="grid grid-cols-3 gap-3 p-4">
        <KpiCard label="今日累计" value={todayTotal} sub={data?.meta?.day ?? ''} accent="violet" />
        <KpiCard label={`近 ${days} 日累计`} value={rangeTotal} sub={`${data?.meta?.range_start} ~ ${data?.meta?.range_end}`} accent="blue" />
        <KpiCard label="本月累计" value={monthTotal} sub={data?.meta?.month ?? ''} accent="emerald" />
      </div>

      {/* 视图切换 + 日数选择 */}
      <div className="flex items-center gap-1.5 px-4 pb-2">
        {([
          { k: 'daily', t: '每日趋势' },
          { k: 'hourly', t: '每小时分布' },
          { k: 'monthly', t: '本月累计' },
        ] as Array<{ k: ViewMode; t: string }>).map(({ k, t }) => (
          <button
            key={k}
            onClick={() => setView(k)}
            className={cn(
              'text-[10px] px-2 py-0.5 rounded border transition-colors',
              view === k
                ? 'bg-primary/15 text-primary border-primary/30'
                : 'text-muted-foreground border-border/40 hover:bg-muted/50'
            )}
          >
            {t}
          </button>
        ))}
        {view === 'daily' && (
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="ml-auto text-[10px] bg-secondary/40 border border-border/40 rounded px-1.5 py-0.5 text-muted-foreground"
          >
            {[7, 14, 30].map((d) => <option key={d} value={d}>近 {d} 日</option>)}
          </select>
        )}
      </div>

      {/* 图表 */}
      <div className="px-4 pb-2">
        {loading ? (
          <div className="h-[350px] flex items-center justify-center text-muted-foreground">
            <RefreshCw className="h-5 w-5 animate-spin opacity-50" />
          </div>
        ) : (
          <EChartsRenderer options={chartOptions} />
        )}
      </div>

      {/* 明细表 */}
      <div className="overflow-auto max-h-[260px] custom-scrollbar px-4 pb-4">
        <DetailTable view={view} data={data} />
      </div>
    </div>
  )
}

// ─── KPI 卡片 ────────────────────────────────────────
function KpiCard({ label, value, sub, accent }: { label: string; value: number; sub: string; accent: 'violet' | 'blue' | 'emerald' }) {
  const color = accent === 'violet' ? 'text-violet-400' : accent === 'blue' ? 'text-blue-400' : 'text-emerald-400'
  return (
    <div className="rounded-lg border border-border/40 bg-secondary/20 p-3">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={cn('text-xl font-bold font-mono mt-1', color)}>{fmt(value)}</div>
      <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{sub}</div>
    </div>
  )
}

// ─── 明细表 ──────────────────────────────────────────
function DetailTable({ view, data }: { view: ViewMode; data: TokenUsageResponse | null }) {
  if (!data) return <div className="py-8 text-center text-muted-foreground text-xs">暂无数据</div>

  const rows: Array<{ key: string; b: Bucket }> = []
  if (view === 'daily') {
    data.daily_range.forEach((d) => rows.push({ key: d.date, b: d }))
  } else if (view === 'hourly') {
    data.hourly.forEach((h) => rows.push({ key: `${String(h.hour).padStart(2, '0')}:00`, b: h }))
  } else {
    rows.push({ key: data.monthly.month, b: data.monthly })
  }

  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md">
        <tr className="border-b border-border/40">
          <th className="px-3 py-2 text-left text-muted-foreground font-medium whitespace-nowrap">{view === 'hourly' ? '小时' : view === 'monthly' ? '月份' : '日期'}</th>
          <th className="px-3 py-2 text-right text-muted-foreground font-medium">Prompt</th>
          <th className="px-3 py-2 text-right text-muted-foreground font-medium">Completion</th>
          <th className="px-3 py-2 text-right text-muted-foreground font-medium">Total</th>
          <th className="px-3 py-2 text-right text-muted-foreground font-medium">Calls</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-y">
        {rows.length === 0 ? (
          <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">暂无数据</td></tr>
        ) : (
          rows.map((r) => (
            <tr key={r.key}>
              <td className="px-3 py-2 text-muted-foreground font-mono whitespace-nowrap">{r.key}</td>
              <td className="px-3 py-2 text-right font-mono">{fmt(r.b.prompt_tokens)}</td>
              <td className="px-3 py-2 text-right font-mono">{fmt(r.b.completion_tokens)}</td>
              <td className="px-3 py-2 text-right font-mono font-semibold text-violet-400">{fmt(r.b.total_tokens)}</td>
              <td className="px-3 py-2 text-right font-mono text-muted-foreground">{fmt(r.b.calls)}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}

// ─── 图表配置 (ECharts 暗黑配色) ─────────────────────
function buildChartOptions(view: ViewMode, data: TokenUsageResponse | null): any {
  const axis = '#334155'
  const label = '#64748b'
  const violet = '#8b5cf6'
  const blue = '#3b82f6'
  const emerald = '#10b981'

  if (!data) return {}

  if (view === 'daily') {
    const x = data.daily_range.map((d) => d.date)
    const total = data.daily_range.map((d) => d.total_tokens)
    const prompt = data.daily_range.map((d) => d.prompt_tokens)
    const comp = data.daily_range.map((d) => d.completion_tokens)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: '#1e293b', borderColor: axis, textStyle: { color: '#e2e8f0' } },
      legend: { data: ['Total', 'Prompt', 'Completion'], textStyle: { color: label }, top: 0 },
      grid: { left: 50, right: 16, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: x, axisLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
      yAxis: { type: 'value', axisLine: { lineStyle: { color: axis } }, splitLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
      series: [
        { name: 'Total', type: 'line', smooth: true, data: total, itemStyle: { color: violet }, areaStyle: { color: 'rgba(139,92,246,0.12)' } },
        { name: 'Prompt', type: 'bar', data: prompt, itemStyle: { color: blue } },
        { name: 'Completion', type: 'bar', data: comp, itemStyle: { color: emerald } },
      ],
    }
  }

  if (view === 'hourly') {
    const x = data.hourly.map((h) => String(h.hour).padStart(2, '0'))
    const total = data.hourly.map((h) => h.total_tokens)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: '#1e293b', borderColor: axis, textStyle: { color: '#e2e8f0' } },
      grid: { left: 50, right: 16, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: x, axisLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
      yAxis: { type: 'value', axisLine: { lineStyle: { color: axis } }, splitLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
      series: [{ name: 'Total', type: 'bar', data: total, itemStyle: { color: violet }, barWidth: '60%' }],
    }
  }

  // monthly：单月柱状（仅 1 根，展示构成）
  const m = data.monthly
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', backgroundColor: '#1e293b', borderColor: axis, textStyle: { color: '#e2e8f0' } },
    grid: { left: 50, right: 16, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: [m.month], axisLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
    yAxis: { type: 'value', axisLine: { lineStyle: { color: axis } }, splitLine: { lineStyle: { color: axis } }, axisLabel: { color: label, fontSize: 10 } },
    series: [
      { name: 'Prompt', type: 'bar', stack: 't', data: [m.prompt_tokens], itemStyle: { color: blue } },
      { name: 'Completion', type: 'bar', stack: 't', data: [m.completion_tokens], itemStyle: { color: emerald } },
    ],
  }
}
