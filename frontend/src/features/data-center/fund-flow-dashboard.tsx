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

interface HkConnectChannel {
  board: string | null
  net_buy: number | null
  net_inflow: number | null
  up: number | null
  down: number | null
  flat: number | null
  index: string | null
  index_chg: number | null
}

interface HkConnectData {
  trade_date: string | null
  total_net_buy: number | null
  unit: string | null
  channels: HkConnectChannel[]
}

interface UsBigOrderItem {
  ticker: string | null
  name: string | null
  net_inflow: number | null
}

interface UsBigOrderData {
  total_net_inflow: number | null
  unit: string | null
  breakdown: UsBigOrderItem[]
  note?: string | null
}

interface DashboardData {
  northbound: FlowPoint | null
  southbound: FlowPoint | null
  hk_connect: HkConnectData | null
  a_share: MarketSectors | null
  hk: MarketSectors | null
  us: MarketSectors | null
  us_big_order: UsBigOrderData | null
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

function SectorPie({ title, sectors, unit, unavailable }: { title: string; sectors: SectorItem[]; unit: string | null; unavailable?: boolean }) {
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
        formatter: (p: any) => {
          const signed = p?.data?.signed
          if (signed == null || Number.isNaN(signed)) return `${p?.name ?? ''}<br/>净流入: --`
          return `${p.name}<br/>净流入: ${signed >= 0 ? '+' : ''}${signed.toFixed(1)} ${unit || ''}`
        },
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
      ) : unavailable ? (
        <div className="h-[220px] flex items-center justify-center text-xs text-amber-500/90">数据源暂不可用 · 恢复后自动重试</div>
      ) : (
        <div className="h-[220px] flex items-center justify-center text-xs text-muted-foreground/60">暂无行业数据</div>
      )}
    </div>
  )
}

// ── 美股板块资金流柱状图 ─────────────────────────────────────────────────

function SectorBar({ title, sectors, unit, unavailable }: { title: string; sectors: SectorItem[]; unit: string | null; unavailable?: boolean }) {
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
          const val = p?.value
          if (val == null || Number.isNaN(val)) return `${p?.name ?? ''}<br/>净流入: --`
          return `${p.name}<br/>净流入: ${val >= 0 ? '+' : ''}${val.toFixed(1)} ${unit || ''}`
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
      ) : unavailable ? (
        <div className="h-[260px] flex items-center justify-center text-xs text-amber-500/90">数据源暂不可用 · 恢复后自动重试</div>
      ) : (
        <div className="h-[260px] flex items-center justify-center text-xs text-muted-foreground/60">暂无板块数据</div>
      )}
    </div>
  )
}

// ── 港股通南向双通道净买额 ───────────────────────────────────────────────

function HkConnectCard({ data }: { data: HkConnectData | null }) {
  if (!data || !data.channels || data.channels.length === 0) {
    // 港股通数据仅在交易日由 AKShare 产生，周末/香港公众假期自然无数据。
    // 空态明确标注"非交易日暂停"，避免用户误以为数据源故障 (bug)。
    const now = new Date()
    const isWeekend = now.getDay() === 0 || now.getDay() === 6
    return (
      <div className="glass-card rounded-lg p-4 flex flex-col gap-2">
        <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <ArrowRightLeft className="h-3.5 w-3.5 text-amber-400" /> 港股通南向双通道净买额
        </div>
        <div className="text-sm text-muted-foreground/60 flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 text-muted-foreground/40" />
          {isWeekend ? '周末非交易日 · 港股通数据暂停更新' : '数据源暂未连通 · 港股通数据缺失'}
        </div>
      </div>
    )
  }
  const total = data.total_net_buy ?? 0
  const positive = total >= 0
  return (
    <div className="glass-card rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <ArrowRightLeft className="h-3.5 w-3.5 text-amber-400" /> 港股通南向双通道净买额
        </span>
        <span className="text-[9px] text-muted-foreground/50 font-mono">交易日: {data.trade_date || '--'}</span>
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-[10px] text-muted-foreground/70 mb-0.5">南向合计净买入</span>
          <span className={cn('text-2xl font-bold font-mono tabular-nums', positive ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>
            {fmt(total)}
            <span className="text-xs ml-1 opacity-70">{data.unit || '亿元'}</span>
          </span>
        </div>
        {positive ? <TrendingUp className="h-5 w-5 text-[#0ecb81]" /> : <TrendingDown className="h-5 w-5 text-[#f6465d]" />}
      </div>

      <div className="grid grid-cols-1 gap-2 border-t border-border/10 pt-2">
        {data.channels.map((c) => {
          const pos = (c.net_buy ?? 0) >= 0
          return (
            <div key={c.board} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-medium text-foreground/90">{c.board}</span>
              <span className="flex items-center gap-2">
                <span className={cn('font-mono tabular-nums', pos ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>{fmt(c.net_buy)}</span>
                <span className="text-muted-foreground/50 font-mono">
                  涨 {c.up ?? 0} / 跌 {c.down ?? 0}
                </span>
                {c.index_chg !== null && c.index_chg !== undefined && (
                  <span className={cn('font-mono', (c.index_chg ?? 0) >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>
                    {(c.index_chg ?? 0) >= 0 ? '▲' : '▼'}
                    {Math.abs(c.index_chg ?? 0).toFixed(2)}%
                  </span>
                )}
              </span>
            </div>
          )
        })}
      </div>

      <div className="text-[9px] text-muted-foreground/50">
        数据来源: AKShare 沪深港通资金流向汇总（南向双通道）· 口径: 港股通(沪)+(深) 成交净买额
      </div>
    </div>
  )
}

// ── 美股主力 / 大单净流入 (Futu 资金分布) ─────────────────────────────────

function UsBigOrderCard({ data }: { data: UsBigOrderData | null }) {
  if (!data || !data.breakdown || data.breakdown.length === 0) {
    return (
      <div className="glass-card rounded-lg p-4 flex flex-col gap-2">
        <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <BarChart3 className="h-3.5 w-3.5 text-sky-400" /> 美股主力 / 大单净流入
        </div>
        <div className="text-sm text-muted-foreground/60">暂无大单数据（Futu 未连接或 ETF 资金分布为空）</div>
      </div>
    )
  }
  const total = data.total_net_inflow ?? 0
  const positive = total >= 0
  return (
    <div className="glass-card rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <BarChart3 className="h-3.5 w-3.5 text-sky-400" /> 美股主力 / 大单净流入
        </span>
        <span className="text-[9px] text-muted-foreground/50">Futu 资金分布</span>
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-[10px] text-muted-foreground/70 mb-0.5">核心 ETF 主力(超大单+大单)净买额</span>
          <span className={cn('text-2xl font-bold font-mono tabular-nums', positive ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>
            {fmt(total)}
            <span className="text-xs ml-1 opacity-70">{data.unit || '亿美元'}</span>
          </span>
        </div>
        {positive ? <TrendingUp className="h-5 w-5 text-[#0ecb81]" /> : <TrendingDown className="h-5 w-5 text-[#f6465d]" />}
      </div>

      <div className="flex flex-col gap-1.5 border-t border-border/10 pt-2">
        <span className="text-[10px] text-muted-foreground/60">净流入贡献 Top</span>
        {data.breakdown.slice(0, 5).map((b) => {
          const pos = (b.net_inflow ?? 0) >= 0
          return (
            <div key={b.ticker} className="flex items-center justify-between text-[11px]">
              <span className="font-medium text-foreground/90">
                {b.name || b.ticker}
                <span className="text-muted-foreground/40 ml-1 font-mono">{b.ticker}</span>
              </span>
              <span className={cn('font-mono tabular-nums', pos ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>{fmt(b.net_inflow)}</span>
            </div>
          )
        })}
      </div>

      <div className="text-[9px] text-muted-foreground/50">{data.note || '基于核心行业 ETF 的 Futu 主力/大单资金分布聚合'}</div>
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
  const [source, setSource] = useState<string>('AKShare')
  const [sourceDegraded, setSourceDegraded] = useState(false)

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
          setSource((body as any)?.source || 'AKShare')
          const allNull =
            inner &&
            [inner.northbound, inner.southbound, inner.a_share, inner.hk, inner.us, inner.us_big_order].every(
              (x) => x == null,
            )
          setSourceDegraded(!!allNull)
        }
      } catch (_e) {
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
          <span
            className={cn(
              'px-1.5 py-0.5 rounded border',
              sourceDegraded
                ? 'bg-amber-500/10 border-amber-500/30 text-amber-500/90'
                : 'bg-secondary/30 border-border/30',
            )}
          >
            数据源: {source}{sourceDegraded ? ' · 暂未连通' : ''}
          </span>
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
      {!loading && !error && data && [data.northbound, data.southbound, data.a_share, data.hk, data.us, data.us_big_order].every((x) => x == null) && (
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
              <SectorPie title="A股行业资金净流入分布" sectors={data.a_share?.sectors ?? []} unit={data.a_share?.unit ?? null} unavailable={!data?.a_share} />
              <div className="flex items-center justify-between text-[9px] text-muted-foreground/50 px-1">
                <span>行业板块口径: {data.a_share?.source || 'AKShare'}</span>
                <span>更新: {fmtTime(data.a_share?.updated_at)}</span>
              </div>
            </div>
          )}

          {tab === 'hk' && (
            <div className="flex flex-col gap-3">
              <FlowCard title="南向资金 (港股通净买入)" point={data.southbound} accent="#f6465d" />
              <HkConnectCard data={data.hk_connect} />
              <SectorPie title="港股通行业资金净流入分布" sectors={data.hk?.sectors ?? []} unit={data.hk?.unit ?? null} unavailable={!data?.hk} />
            </div>
          )}

          {tab === 'us' && (
            <div className="flex flex-col gap-3">
              <SectorBar title="美股板块 ETF 资金净流入" sectors={data.us?.sectors ?? []} unit={data.us?.unit ?? null} unavailable={!data?.us} />
              <UsBigOrderCard data={data.us_big_order} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FlowCard title="北向资金 (参照)" point={data.northbound} accent="#0ecb81" />
                <FlowCard title="南向资金 (参照)" point={data.southbound} accent="#f6465d" />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default FundFlowDashboardModule
