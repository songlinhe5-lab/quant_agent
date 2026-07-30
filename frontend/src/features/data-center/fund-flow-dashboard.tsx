import React, { useEffect, useState } from 'react'
import { ArrowRightLeft, TrendingUp, TrendingDown, Loader2, AlertTriangle, PieChart, BarChart3, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import { MiniTrendLine } from './shared'

// ── 类型 ────────────────────────────────────────────────────────────────

interface FlowPoint {
  net_inflow: number | null
  weekly: number | null
  monthly: number | null
  unit: string | null
  date: string | null
  sparkline: number[] | null
  history: number[] | null
}

interface SectorItem {
  name: string | null
  net_inflow: number | null
  change_pct?: number | null
}

interface MarketSectors {
  sectors: SectorItem[]
  unit: string | null
  updated_at?: string | null
  source?: string | null
}

interface DashboardData {
  northbound: FlowPoint | null
  southbound: FlowPoint | null
  a_share: MarketSectors | null
  hk: MarketSectors | null
  us: MarketSectors | null
}

type Period = 'day' | 'week' | 'month'
type MarketTab = 'a' | 'hk' | 'us'

// ── 工具 ────────────────────────────────────────────────────────────────

function fmt(v: number | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '--'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}`
}

function fmtTime(s: string | null | undefined): string {
  if (!s) return '--'
  try {
    return new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return '--'
  }
}

// ── 北向/南向 大数字卡片 ─────────────────────────────────────────────────

function FlowCard({ title, point, accent }: { title: string; point: FlowPoint | null; accent: string }) {
  const [period, setPeriod] = useState<Period>('day')
  if (!point) {
    return (
      <div className="glass-card rounded-lg p-4 flex flex-col gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{title}</div>
        <div className="text-sm text-muted-foreground/60">暂无数据</div>
      </div>
    )
  }
  const raw = period === 'day' ? point.net_inflow : period === 'week' ? point.weekly : point.monthly
  const positive = (raw ?? 0) >= 0
  const spark = point.history && point.history.length >= 2 ? point.history : point.sparkline
  const periodLabel = period === 'day' ? '当日' : period === 'week' ? '近一周' : '近一月'

  return (
    <div className="glass-card rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <ArrowRightLeft className="h-3.5 w-3.5" style={{ color: accent }} />
          {title}
        </span>
        <div className="flex items-center gap-0.5 bg-secondary/30 rounded-md p-0.5">
          {(['day', 'week', 'month'] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-bold transition-colors',
                period === p ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {p === 'day' ? '日' : p === 'week' ? '周' : '月'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-[10px] text-muted-foreground/70 mb-0.5">{periodLabel}净流入</span>
          <span className={cn('text-2xl font-bold font-mono tabular-nums', positive ? 'text-[#059669] dark:text-[#0ecb81]' : 'text-[#e11d48] dark:text-[#f6465d]')}>
            {fmt(raw)}
            <span className="text-xs ml-1 opacity-70">{point.unit || ''}</span>
          </span>
        </div>
        {spark && spark.length >= 2 && (
          <div className="opacity-80">
            {positive ? <TrendingUp className="h-4 w-4 text-[#0ecb81]" /> : <TrendingDown className="h-4 w-4 text-[#f6465d]" />}
            <div className="mt-1"><MiniTrendLine data={spark} isPositive={positive} /></div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-[9px] text-muted-foreground/50 border-t border-border/10 pt-1.5">
        <span>交易日: {point.date || '--'}</span>
        {point.weekly !== null && point.monthly !== null && (
          <span className="font-mono">
            周 {fmt(point.weekly)} · 月 {fmt(point.monthly)}
          </span>
        )}
      </div>
    </div>
  )
}

// ── 行业分布饼图 ─────────────────────────────────────────────────────────

function SectorPie({ title, sectors, unit }: { title: string; sectors: SectorItem[]; unit: string | null }) {
  const top = [...sectors].sort((a, b) => Math.abs(b.net_inflow ?? 0) - Math.abs(a.net_inflow ?? 0)).slice(0, 12)
  const ref = useEChart(() => {
    if (!top.length) return null
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: ECHART_DARK.tooltipBg,
        borderColor: '#334155',
        textStyle: { color: ECHART_DARK.text },
        formatter: (p: any) => `${p.name}<br/>净流入: ${p.data.signed >= 0 ? '+' : ''}${p.data.signed.toFixed(1)} ${unit || ''}`,
      },
      legend: { show: false },
      series: [
        {
          type: 'pie',
          radius: ['42%', '72%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#0f172a', borderWidth: 2, borderRadius: 4 },
          label: { color: ECHART_DARK.text, fontSize: 10, formatter: '{b}' },
          labelLine: { lineStyle: { color: '#334155' } },
          data: top.map((it) => ({
            name: it.name || '未知',
            value: Math.max(0.01, Math.abs(it.net_inflow ?? 0)),
            signed: it.net_inflow ?? 0,
            itemStyle: { color: (it.net_inflow ?? 0) >= 0 ? ECHART_DARK.up : ECHART_DARK.down },
          })),
        },
      ],
    }
  }, [sectors, unit])

  return (
    <div className="glass-card rounded-lg p-3 flex flex-col">
      <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5 mb-1">
        <PieChart className="h-3.5 w-3.5 text-sky-400" /> {title}
      </div>
      {top.length ? (
        <div ref={ref} className="w-full h-[220px]" />
      ) : (
        <div className="h-[220px] flex items-center justify-center text-xs text-muted-foreground/60">暂无行业数据</div>
      )}
    </div>
  )
}

// ── 美股板块资金流柱状图 ─────────────────────────────────────────────────

function SectorBar({ title, sectors, unit }: { title: string; sectors: SectorItem[]; unit: string | null }) {
  const sorted = [...sectors].sort((a, b) => (a.net_inflow ?? 0) - (b.net_inflow ?? 0))
  const ref = useEChart(() => {
    if (!sorted.length) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 90, right: 24, top: 12, bottom: 12 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: ECHART_DARK.tooltipBg,
        borderColor: '#334155',
        textStyle: { color: ECHART_DARK.text },
        formatter: (ps: any) => {
          const p = Array.isArray(ps) ? ps[0] : ps
          return `${p.name}<br/>净流入: ${p.value >= 0 ? '+' : ''}${p.value.toFixed(1)} ${unit || ''}`
        },
      },
      xAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#64748b', fontSize: 9 },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((i) => i.name || '未知'),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: ECHART_DARK.text, fontSize: 10 },
      },
      series: [
        {
          type: 'bar',
          barWidth: '58%',
          data: sorted.map((i) => ({
            value: i.net_inflow ?? 0,
            itemStyle: { color: (i.net_inflow ?? 0) >= 0 ? ECHART_DARK.up : ECHART_DARK.down, borderRadius: [0, 3, 3, 0] },
          })),
        },
      ],
    }
  }, [sectors, unit])

  return (
    <div className="glass-card rounded-lg p-3 flex flex-col">
      <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5 mb-1">
        <BarChart3 className="h-3.5 w-3.5 text-sky-400" /> {title}
      </div>
      {sorted.length ? (
        <div ref={ref} className="w-full h-[260px]" />
      ) : (
        <div className="h-[260px] flex items-center justify-center text-xs text-muted-foreground/60">暂无板块数据</div>
      )}
    </div>
  )
}

// ── 信息条（未接入数据源诚实提示） ───────────────────────────────────────

function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-1.5 text-[10px] text-amber-500/90 dark:text-amber-400/90 bg-amber-500/10 border border-amber-500/20 rounded-md px-2 py-1.5">
      <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
      <span>{children}</span>
    </div>
  )
}

// ── 主组件 ──────────────────────────────────────────────────────────────

export function FundFlowDashboardModule() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<MarketTab>('a')
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await apiClient.get('/macro/capital-flow-dashboard')
        const body: any = res?.data ?? res
        const inner: DashboardData = body?.data ?? body
        if (alive) {
          setData(inner)
          setUpdatedAt(inner ? fmtTime((body as any)?.updated_at) : null)
        }
      } catch (e) {
        if (alive) setError('资金流看板数据获取失败，请稍后重试')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const tabs: { key: MarketTab; label: string }[] = [
    { key: 'a', label: '🇨🇳 A股 · 北向' },
    { key: 'hk', label: '🇭🇰 港股 · 南向' },
    { key: 'us', label: '🇺🇸 美股 · 板块' },
  ]

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* 顶栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4 text-sky-500 dark:text-sky-400" />
          <h1 className="text-sm font-bold tracking-wide">北向 / 南向资金实时看板</h1>
        </div>
        <div className="flex items-center gap-2 text-[9px] font-mono text-muted-foreground/60">
          <span className="flex items-center gap-1">
            <Clock className="h-2.5 w-2.5" /> 更新: {updatedAt || '加载中'}
          </span>
          <span className="px-1.5 py-0.5 rounded bg-secondary/30 border border-border/30">数据源: AKShare</span>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 bg-secondary/30 rounded-lg p-1 w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-bold transition-colors',
              tab === t.key ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 加载 / 错误 / 空态 */}
      {loading && (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-16">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载资金流数据中…
        </div>
      )}
      {!loading && error && (
        <div className="flex items-center justify-center gap-2 text-sm text-amber-500 py-16">
          <AlertTriangle className="h-4 w-4" /> {error}
        </div>
      )}
      {!loading && !error && data && (data.northbound || data.southbound || data.a_share || data.hk || data.us) === null && (
        <div className="flex flex-col items-center justify-center gap-2 text-sm text-muted-foreground py-16">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <span>当前所有资金流数据源暂不可用（AKShare / 互联互通），请检查网络后重试。</span>
        </div>
      )}

      {/* 内容 */}
      {!loading && !error && data && (
        <>
          {tab === 'a' && (
            <div className="flex flex-col gap-3">
              <FlowCard title="北向资金 (外资买 A 股)" point={data.northbound} accent="#0ecb81" />
              <SectorPie title="A股行业资金净流入分布" sectors={data.a_share?.sectors ?? []} unit={data.a_share?.unit ?? null} />
              <div className="flex items-center justify-between text-[9px] text-muted-foreground/50 px-1">
                <span>行业板块口径: {data.a_share?.source || 'AKShare'}</span>
                <span>更新: {fmtTime(data.a_share?.updated_at)}</span>
              </div>
            </div>
          )}

          {tab === 'hk' && (
            <div className="flex flex-col gap-3">
              <FlowCard title="南向资金 (港股通净买入)" point={data.southbound} accent="#f6465d" />
              <SectorPie title="港股通行业资金净流入分布" sectors={data.hk?.sectors ?? []} unit={data.hk?.unit ?? null} />
              <InfoNote>
                港股通十大成交榜 / 个股持仓明细 (沪深港通机构托管行) 数据源尚未接入，当前仅展示行业维度南向分布。
              </InfoNote>
            </div>
          )}

          {tab === 'us' && (
            <div className="flex flex-col gap-3">
              <SectorBar title="美股板块 ETF 资金净流入" sectors={data.us?.sectors ?? []} unit={data.us?.unit ?? null} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FlowCard title="北向资金 (参照)" point={data.northbound} accent="#0ecb81" />
                <FlowCard title="南向资金 (参照)" point={data.southbound} accent="#f6465d" />
              </div>
              <InfoNote>
                美股「大单 (Block Trade) 净流入」与「机构持仓变化 Tide Chart」所需的逐笔大单 / 13F 持仓数据源尚未接入，当前以板块 ETF 资金流代理展示。
              </InfoNote>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default FundFlowDashboardModule
