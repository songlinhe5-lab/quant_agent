'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Loader2,
  Clock,
  CalendarDays,
  TrendingUp,
  Coins,
  Rocket,
  CalendarClock,
  Settings2,
  Globe2,
  Newspaper,
  LineChart,
  Gauge,
} from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { AssetButton } from '@/features/data-center/shared'
import { MacroChartPanel } from '@/features/data-center/macro-chart'
import { NewsStream } from '@/features/data-center/news-stream'
import { FedWatchPanel } from '@/features/options/fed-watch-panel'
import { useDashboardData } from '@/features/data-center/use-dashboard-data'
import { cn } from '@/lib/utils'
import {
  filterVisibleCategories,
  formatTimeInZone,
  categoryAnchorId,
  type CalendarCategoryView,
} from './utils'

// 子 tab 列表（对齐 Figma 设计稿：经济日历/财报/分红/新股/交易时段/利率路径/FRED 图表/快讯情感）
// Markets（全球市场行情）已上移到模块顶部默认展示，不占子 tab 位。
const TABS = [
  { id: 'economic', label: '经济日历', icon: CalendarDays },
  { id: 'earnings', label: '财报', icon: TrendingUp },
  { id: 'dividends', label: '分红', icon: Coins },
  { id: 'ipos', label: '新股', icon: Rocket },
  { id: 'hours', label: '交易时段', icon: CalendarClock },
  { id: 'fedwatch', label: '利率路径', icon: Gauge },
  { id: 'fred', label: 'FRED 图表', icon: LineChart },
  { id: 'news', label: '快讯情感', icon: Newspaper },
] as const

type TabId = (typeof TABS)[number]['id']

const TIMEZONES = [
  { code: 'Asia/Hong_Kong', label: 'HKT' },
  { code: 'America/New_York', label: 'ET' },
  { code: 'Etc/UTC', label: 'UTC' },
  { code: 'Asia/Tokyo', label: 'TTY' },
]

// ── 单卡片（复用 data-center 的 AssetButton，叠加 STALE 角标）────────────
function TileCard({ tile }: { tile: any }) {
  const asset = {
    symbol: tile.symbol,
    name: tile.display_name,
    value: tile.price,
    change: tile.change_pct,
    sparkline: tile.sparkline || [],
    data_source: tile.source,
    updated_at: tile.updated_at,
    source: tile.source,
  }
  return (
    <div className="relative">
      <AssetButton asset={asset} />
      {tile.is_stale && (
        <span className="absolute top-1 right-1 text-[8px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30 px-1 rounded-sm leading-none">
          STALE
        </span>
      )}
    </div>
  )
}

// ── Markets Tab：类目侧栏 + 横向滚动卡片行 ──────────────────────────────
function MarketsView({ snapshot }: { snapshot: any }) {
  const categories: CalendarCategoryView[] = snapshot?.categories || []
  const [hidden, setHidden] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('quant_calendars_hidden') || '[]')
    } catch {
      return []
    }
  })
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const visible = filterVisibleCategories(categories, hidden)

  const toggleHidden = (cat: string) => {
    setHidden((prev) => {
      const next = prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
      localStorage.setItem('quant_calendars_hidden', JSON.stringify(next))
      return next
    })
  }

  const scrollTo = (cat: string) => {
    rowRefs.current[cat]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const scrollRow = (cat: string, dir: number) => {
    const el = rowRefs.current[cat]
    if (el) el.scrollBy({ left: dir * 600, behavior: 'smooth' })
  }

  if (categories.length === 0) {
    return <div className="text-sm text-muted-foreground p-4">暂无行情数据</div>
  }

  return (
    <div className="flex gap-3 h-full">
      {/* 类目侧栏 */}
      <aside className="w-[176px] shrink-0 hidden lg:block">
        <div className="glass-card rounded-lg p-2 space-y-0.5 sticky top-2">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground px-2 py-1.5">
            类目
          </div>
          {categories.map((c) => (
            <button
              key={c.category}
              onClick={() => scrollTo(c.category)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-secondary/60 transition-colors text-left"
            >
              <span
                className={cn(
                  'w-1.5 h-1.5 rounded-full shrink-0',
                  c.is_market_open
                    ? 'bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.6)]'
                    : 'bg-muted-foreground/30',
                )}
              />
              <span className="flex-1 text-xs truncate text-foreground/90">{c.display_name}</span>
              <span className="text-[9px] text-muted-foreground tabular-nums">{c.tiles.length}</span>
            </button>
          ))}
          <details className="px-2 pt-1.5 mt-1 border-t border-border/20">
            <summary className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer hover:text-foreground">
              <Settings2 className="h-3 w-3" /> 自定义类目
            </summary>
            <div className="mt-1.5 space-y-0.5">
              {categories.map((c) => (
                <label key={c.category} className="flex items-center gap-2 text-[10px] py-0.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!hidden.includes(c.category)}
                    onChange={() => toggleHidden(c.category)}
                    className="accent-primary"
                  />
                  <span className="truncate">{c.display_name}</span>
                </label>
              ))}
            </div>
          </details>
        </div>
      </aside>

      {/* 主滚动区：每类目一行横向滚动 */}
      <div className="flex-1 min-w-0 space-y-3.5 overflow-y-auto pr-0.5">
        {visible.map((c) => (
          <section key={c.category} id={categoryAnchorId(c.category)}>
            <div className="flex items-center gap-2 px-1 mb-1.5">
              <span
                className={cn(
                  'w-1.5 h-1.5 rounded-full shrink-0',
                  c.is_market_open
                    ? 'bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.6)]'
                    : 'bg-muted-foreground/30',
                )}
              />
              <h3 className="text-xs font-semibold text-foreground/90">{c.display_name}</h3>
              <span
                className={cn(
                  'text-[9px] px-1.5 py-0.5 rounded-full',
                  c.is_market_open
                    ? 'bg-emerald-500/10 text-emerald-400'
                    : 'bg-muted-foreground/10 text-muted-foreground',
                )}
              >
                {c.is_market_open ? '交易中' : '休市'}
              </span>
              <button
                onClick={() => scrollRow(c.category, -1)}
                className="ml-auto md:hidden text-muted-foreground hover:text-foreground text-xs"
                aria-label="向左滚动"
              >
                ‹
              </button>
              <button
                onClick={() => scrollRow(c.category, 1)}
                className="md:hidden text-muted-foreground hover:text-foreground text-xs"
                aria-label="向右滚动"
              >
                ›
              </button>
            </div>
            <div
              ref={(el) => {
                rowRefs.current[c.category] = el
              }}
              className="flex gap-3 overflow-x-auto scrollbar-thin pb-1 px-0.5 min-w-max"
            >
              {c.tiles.map((t) => (
                <TileCard key={t.symbol} tile={t} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

// ── 通用事件表（Economic / Earnings / Dividends / IPOs）─────────────────
function ScheduleTable({ columns, rows, empty }: { columns: string[]; rows: any[][]; empty: string }) {
  if (rows.length === 0) {
    return <div className="text-sm text-muted-foreground p-4">{empty}</div>
  }
  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/30 text-muted-foreground">
              {columns.map((col) => (
                <th key={col} className="text-left font-medium px-3 py-2 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border/10 hover:bg-secondary/30 transition-colors">
                {row.map((cell, j) => (
                  <td key={j} className="px-3 py-2 whitespace-nowrap text-foreground/90">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function impactBadge(impact: string) {
  const map: Record<string, string> = {
    high: 'bg-red-500/15 text-red-400',
    medium: 'bg-amber-500/15 text-amber-400',
    low: 'bg-slate-500/15 text-slate-400',
  }
  return map[impact] || map.low
}

// 倒计时：基于事件 date（ISO，可能含空格）与目标时刻差值，返回 "X天Y时"/"Y时Z分"/"Z分"/已发布
function countdown(targetIso: string, now: number) {
  if (!targetIso) return null
  const t = new Date(targetIso.replace(' ', 'T')).getTime()
  if (Number.isNaN(t)) return null
  const diff = t - now
  if (diff <= 0) return { label: '已发布', past: true }
  const totalMin = Math.floor(diff / 60000)
  const d = Math.floor(totalMin / 1440)
  const h = Math.floor((totalMin % 1440) / 60)
  const m = totalMin % 60
  const label = d > 0 ? `${d}天${h}时` : h > 0 ? `${h}时${m}分` : `${m}分`
  return { label, past: false }
}

function EconomicView() {
  const [loading, setLoading] = useState(true)
  const [events, setEvents] = useState<any[]>([])
  const [regionFilter, setRegionFilter] = useState<string>('all')
  // 默认 'core'：优先展示核心（数据中最高影响级别）经济数据；无核心则降级显示级别高的项
  const [impactFilter, setImpactFilter] = useState<string>('core')
  const [dateFilter, setDateFilter] = useState<string>('all')
  // MACRO-05：高危事件倒计时实时刷新（精度到分钟）
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    let alive = true
    apiClient
      .get('/macro/calendar', { days_ahead: 14 })
      .then((res: any) => {
        // 兼容多种信封结构：data.data 可能是数组 / {data:[...]} / null
        const raw = res?.data?.data
        const list = Array.isArray(raw)
          ? raw
          : Array.isArray(raw?.data)
            ? (raw.data as any[])
            : []
        if (!alive) return
        setEvents(list)
      })
      .catch(() => alive && setEvents([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>

  // 派生筛选选项
  const regions = Array.from(new Set(events.map((e) => e.country).filter(Boolean)))
  const impacts = ['high', 'medium', 'low']
  const dates = Array.from(new Set(events.map((e) => String(e.date || '').slice(0, 10)).filter(Boolean)))

  // 数据中实际存在的影响级别（按高→低），用于 'core' 默认态回退：无核心(high)则显示级别最高的项
  const presentImpacts = impacts.filter((i) => events.some((e) => e.impact === i))
  const topImpact = presentImpacts[0] ?? 'high'
  const effectiveImpact = impactFilter === 'core' ? topImpact : impactFilter

  const filtered = events.filter((e) => {
    if (regionFilter !== 'all' && e.country !== regionFilter) return false
    if (effectiveImpact !== 'all' && e.impact !== effectiveImpact) return false
    if (dateFilter !== 'all' && String(e.date || '').slice(0, 10) !== dateFilter) return false
    return true
  })

  // 影响度 → 星级
  const stars = (impact: string) => {
    const n = impact === 'high' ? 3 : impact === 'medium' ? 2 : impact === 'low' ? 1 : 0
    const cls = impact === 'high' ? 'text-rose-400' : impact === 'medium' ? 'text-amber-400' : 'text-slate-500'
    return { n, cls }
  }
  // 地区 → 国旗 emoji（轻量映射，未覆盖回退）
  const flag = (country: string) => {
    const m: Record<string, string> = { '美国': '🇺🇸', 'US': '🇺🇸', '中国': '🇨🇳', 'CN': '🇨🇳', '欧元区': '🇪🇺', 'EU': '🇪🇺', '澳洲': '🇦🇺', 'AU': '🇦🇺', '英国': '🇬🇧', 'UK': '🇬🇧', '日本': '🇯🇵', 'JP': '🇯🇵', '加拿大': '🇨🇦', 'CA': '🇨🇦', '新西兰': '🇳🇿', 'NZ': '🇳🇿', '香港': '🇭🇰', 'HK': '🇭🇰' }
    return m[country] || '🌐'
  }

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      {/* 面板标题 + 右上筛选下拉（对齐 Figma 设计稿：地区 / 级别 / 日期） */}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">经济日历 · 央行事件</span>
        <div className="ml-auto flex items-center gap-1.5 text-[10px]">
          <select value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)} className="bg-secondary/50 border border-border/30 rounded px-1.5 py-0.5 text-muted-foreground focus:outline-none">
            <option value="all">地区 ▾</option>
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={impactFilter} onChange={(e) => setImpactFilter(e.target.value)} className="bg-secondary/50 border border-border/30 rounded px-1.5 py-0.5 text-muted-foreground focus:outline-none">
            <option value="core">核心 ▾</option>
            <option value="all">全部</option>
            {impacts.map((i) => <option key={i} value={i}>{i === 'high' ? '高' : i === 'medium' ? '中' : '低'}</option>)}
          </select>
          <select value={dateFilter} onChange={(e) => setDateFilter(e.target.value)} className="bg-secondary/50 border border-border/30 rounded px-1.5 py-0.5 text-muted-foreground focus:outline-none">
            <option value="all">日期 ▾</option>
            {dates.map((d) => <option key={d} value={d}>{d.slice(5)}</option>)}
          </select>
        </div>
      </div>

      {/* 表头 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/30 text-muted-foreground">
              <th className="text-left font-medium px-3 py-2 whitespace-nowrap">日期</th>
              <th className="text-left font-medium px-3 py-2 whitespace-nowrap">时间</th>
              <th className="text-left font-medium px-3 py-2 whitespace-nowrap">地区</th>
              <th className="text-left font-medium px-3 py-2 whitespace-nowrap">事件</th>
              <th className="text-left font-medium px-3 py-2 whitespace-nowrap">级别</th>
              <th className="text-right font-medium px-3 py-2 whitespace-nowrap">实际</th>
              <th className="text-right font-medium px-3 py-2 whitespace-nowrap">预期</th>
              <th className="text-right font-medium px-3 py-2 whitespace-nowrap">前值</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="text-center text-muted-foreground py-6">暂无宏观经济事件</td></tr>
            )}
            {filtered.map((e, i) => {
              const s = stars(e.impact)
              const cd = e.impact === 'high' ? countdown(e.date, now) : null
              return (
                <tr key={i} className="border-b border-border/10 hover:bg-secondary/30 transition-colors">
                  <td className="px-3 py-2 whitespace-nowrap font-mono">{String(e.date || '').slice(0, 10) || '--'}</td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono">{String(e.date || '').slice(11, 16) || '--'}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{flag(e.country)} {e.country || '--'}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-foreground/90">{e.event || '--'}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {s.n > 0 ? <span className={s.cls}>{Array.from({ length: s.n }).map(() => '★').join('')}</span> : <span className="text-muted-foreground/40">—</span>}
                    {cd && (
                      <span
                        className={cn(
                          'ml-1.5 inline-flex items-center gap-0.5 px-1 rounded text-[9px] tabular-nums',
                          cd.past ? 'bg-muted-foreground/10 text-muted-foreground' : 'bg-red-500/15 text-red-400',
                        )}
                      >
                        <Clock className="h-2.5 w-2.5" />
                        {cd.label}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-right">{e.actual ?? '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-right text-muted-foreground">{e.estimate ?? '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-right text-muted-foreground">{e.previous ?? e.previous_value ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 底部 footer（对齐设计稿：数据源 + 更新于） */}
      <div className="px-4 py-1.5 border-t border-border/20 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>数据源:AKShare · DBNomics · FRED</span>
        <span>更新于 07:40</span>
      </div>
    </div>
  )
}

function EarningsView() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<any[][]>([])
  useEffect(() => {
    let alive = true
    apiClient
      .get('/macro/earnings', { days_ahead: 7 })
      .then((res: any) => {
        const items = (res?.data?.data as any[]) || []
        if (!alive) return
        setRows(
          items.slice(0, 100).map((e) => [
            e.date || e.symbol || '--',
            e.symbol || '--',
            e.name || '--',
            e.eps?.actual ?? e.epsActual ?? '—',
            e.eps?.estimate ?? e.epsEstimate ?? '—',
            e.revenue?.actual ?? e.revenueActual ?? '—',
          ]),
        )
      })
      .catch(() => alive && setRows([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>
  return (
    <ScheduleTable
      columns={['日期', '代码', '公司', 'EPS 实际', 'EPS 预期', '营收实际']}
      rows={rows}
      empty="暂无财报日程"
    />
  )
}

function DividendsView() {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [rows, setRows] = useState<any[][]>([])
  useEffect(() => {
    let alive = true
    apiClient
      .get('/calendars/dividends')
      .then((res: any) => {
        const body = res?.data
        if (!alive) return
        if (body?.status !== 'success') {
          setStatus(body?.message || '分红日历暂不可用')
          setRows([])
          return
        }
        const items = (body?.data as any[]) || []
        setRows(
          items.map((d) => [
            d.paymentDate || d.recordDate || '--',
            d.symbol || '--',
            d.amount || '—',
            d.rate || '—',
          ]),
        )
      })
      .catch(() => alive && setRows([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>
  if (status) return <div className="text-sm text-amber-400 p-4">{status}</div>
  return (
    <ScheduleTable columns={['派息日', '代码', '金额', '收益率']} rows={rows} empty="暂无分红日程" />
  )
}

function IPOsView() {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [rows, setRows] = useState<any[][]>([])
  useEffect(() => {
    let alive = true
    apiClient
      .get('/calendars/ipos')
      .then((res: any) => {
        const body = res?.data
        if (!alive) return
        if (body?.status !== 'success') {
          setStatus(body?.message || 'IPO 日历暂不可用')
          setRows([])
          return
        }
        const items = (body?.data as any[]) || []
        setRows(
          items.map((p) => [
            p.date || '--',
            p.symbol || '--',
            p.name || '--',
            p.exchange || '—',
            p.price || '—',
          ]),
        )
      })
      .catch(() => alive && setRows([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>
  if (status) return <div className="text-sm text-amber-400 p-4">{status}</div>
  return (
    <ScheduleTable columns={['日期', '代码', '公司', '交易所', '发行价']} rows={rows} empty="暂无 IPO 日程" />
  )
}

// ── Hours Tab：世界时钟 + 市场交易时段矩阵 ─────────────────────────────
function HoursView() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    let alive = true
    apiClient
      .get('/calendars/hours')
      .then((res: any) => {
        if (alive) setData(res?.data?.data || null)
      })
      .catch(() => alive && setData(null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>
  if (!data) return <div className="text-sm text-muted-foreground p-4">暂无交易时段数据</div>

  return (
    <div className="space-y-3">
      {/* 世界时钟卡片 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {data.timezones.map((z: any) => (
          <div key={z.code} className="glass-card rounded-lg p-3">
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground uppercase tracking-wider">
              <Globe2 className="h-3 w-3" />
              {z.label}
            </div>
            <div className="text-lg font-bold font-mono tabular-nums mt-1">{z.current_time?.slice(11) || '--'}</div>
            <div className="text-[10px] text-muted-foreground">{z.current_time?.slice(0, 10) || '--'}</div>
          </div>
        ))}
      </div>
      {/* 市场时段矩阵 */}
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/30 text-muted-foreground">
                <th className="text-left font-medium px-3 py-2 whitespace-nowrap">市场</th>
                <th className="text-left font-medium px-3 py-2 whitespace-nowrap">当地开盘</th>
                <th className="text-left font-medium px-3 py-2 whitespace-nowrap">当地收盘</th>
                <th className="text-left font-medium px-3 py-2 whitespace-nowrap">状态</th>
                <th className="text-left font-medium px-3 py-2 whitespace-nowrap">下一切换</th>
              </tr>
            </thead>
            <tbody>
              {data.markets.map((m: any, i: number) => (
                <tr key={i} className="border-b border-border/10 hover:bg-secondary/30 transition-colors">
                  <td className="px-3 py-2 whitespace-nowrap text-foreground/90">{m.name}</td>
                  <td className="px-3 py-2 font-mono tabular-nums">{m.open || '—'}</td>
                  <td className="px-3 py-2 font-mono tabular-nums">{m.close || '—'}</td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        'px-1.5 py-0.5 rounded-full text-[10px]',
                        m.is_open ? 'bg-emerald-500/15 text-emerald-400' : 'bg-muted-foreground/10 text-muted-foreground',
                      )}
                    >
                      {m.is_open ? '交易中' : '休市'}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums text-muted-foreground">
                    {m.next_session_change ? m.next_session_change.slice(0, 16).replace('T', ' ') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── 主模块 ─────────────────────────────────────────────────────────────
export function CalendarsModule() {
  const [tab, setTab] = useState<TabId>('economic')
  const [tz, setTz] = useState('Asia/Hong_Kong')
  const [snapshot, setSnapshot] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [last, setLast] = useState('')
  const d = useDashboardData()

  const loadSnapshot = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await apiClient.get('/calendars/snapshot')
      if (res?.data?.status === 'success') {
        setSnapshot(res.data.data)
        setLast(formatTimeInZone(res.data.updated_at, tz))
      }
    } catch {
      /* 静默：保留上次数据 */
    } finally {
      setLoading(false)
    }
  }, [tz])

  useEffect(() => {
    loadSnapshot()
    const iv = setInterval(loadSnapshot, 60000)
    return () => clearInterval(iv)
  }, [loadSnapshot])

  // 多时钟显示（NY/HK/TYO + 日期）
  const [now, setNow] = useState<Date>(new Date())
  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(iv)
  }, [])
  const cityClocks = [
    { code: 'NY',  zone: 'America/New_York' },
    { code: 'HK',  zone: 'Asia/Hong_Kong' },
    { code: 'TYO', zone: 'Asia/Tokyo' },
  ]
  const clockText = cityClocks
    .map((c) => {
      const t = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: c.zone }).format(now)
      return `${c.code} ${t}`
    })
    .join('  ')
  const todayHKT = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Hong_Kong' }).format(now)

  return (
    <div className="space-y-3 h-full flex flex-col">
      {/* 标题 + 多时钟显示（对齐 Figma 设计稿：市场脉搏 + 多时区时钟 + 日期） */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-primary" />
        <h1 className="text-base font-bold tracking-tight">全球市场日历</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          Calendars
        </span>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground ml-2" />}
        {/* 右侧多时区时钟 + 日期（设计稿右上角） */}
        <div className="ml-auto flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
          <span className="hidden lg:inline">{clockText}</span>
          <span className="bg-secondary/50 border border-border/30 rounded px-2 py-0.5">{todayHKT} HKT</span>
        </div>
        {/* 时区切换（保留向下选择，便于切时区视角） */}
        <select
          value={tz}
          onChange={(e) => setTz(e.target.value)}
          className="text-[10px] bg-secondary/50 border border-border/30 rounded px-1.5 py-1 font-mono text-muted-foreground focus:outline-none"
          aria-label="时区切换"
        >
          {TIMEZONES.map((z) => (
            <option key={z.code} value={z.code}>
              {z.label}
            </option>
          ))}
        </select>
      </div>

      {/* 多源聚合状态（对齐 Figma 设计稿：AKShare / DBNomics / FRED 圆点） */}
      <div className="flex items-center gap-3 px-1 text-[10px] text-muted-foreground">
        <span className="font-semibold uppercase tracking-wide">多源聚合状态</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--bull))]" />AKShare</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-purple-400" />DBNomics</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" />FRED</span>
        <span className="ml-2 text-muted-foreground/80">宏观日历多源聚合完成</span>
      </div>

      {/* AI 主脑前瞻推演卡（对齐 Figma 设计稿：紫色顶部 + 标题 + 文字说明） */}
      <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 px-4 py-3">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[10px] font-bold text-purple-400 tracking-wide">AI 生成 · 仅供学习</span>
          <span className="text-sm font-bold text-foreground">主脑前瞻推演</span>
        </div>
        <p className="text-xs text-foreground/80 leading-relaxed">
          本周焦点 - 新西兰7月电子销售数据，月度与年度趋势显示消费价格敏感度上升，或对NZD交叉盘形成提振，关注USDCAD、NZDJPY联动。
        </p>
      </div>

      {/* 顶部：全球市场行情（Markets）默认展示 — 不占子 tab 位，对齐 Figma 设计稿 */}
      <MarketsView snapshot={snapshot} />

      {/* 子 tab 栏（8 个，对齐设计稿：经济日历/财报/分红/新股/交易时段/利率路径/FRED 图表/快讯情感） */}
      <div className="flex items-center gap-0.5 border-b border-border/30 overflow-x-hidden">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors',
                active
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          )
        })}
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 min-h-0">
        {tab === 'economic' && <EconomicView />}
        {tab === 'earnings' && <EarningsView />}
        {tab === 'dividends' && <DividendsView />}
        {tab === 'ipos' && <IPOsView />}
        {tab === 'hours' && <HoursView />}
        {tab === 'fedwatch' && <FedWatchPanel />}
        {tab === 'fred' && <MacroChartPanel />}
        {tab === 'news' && (
          <NewsStream
            news={d.news}
            visibleNewsCount={d.visibleNewsCount}
            setVisibleNewsCount={d.setVisibleNewsCount}
          />
        )}
      </div>
    </div>
  )
}

export default CalendarsModule
