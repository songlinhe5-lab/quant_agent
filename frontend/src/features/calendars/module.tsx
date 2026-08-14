'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Loader2,
  Clock,
  LineChart,
  CalendarDays,
  TrendingUp,
  Coins,
  Rocket,
  CalendarClock,
  Settings2,
  Globe2,
} from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { AssetButton } from '@/features/data-center/shared'
import { cn } from '@/lib/utils'
import {
  filterVisibleCategories,
  formatTimeInZone,
  categoryAnchorId,
  type CalendarCategoryView,
} from './utils'

const TABS = [
  { id: 'markets', label: 'Markets', icon: LineChart },
  { id: 'economic', label: 'Economic', icon: CalendarDays },
  { id: 'earnings', label: 'Earnings', icon: TrendingUp },
  { id: 'dividends', label: 'Dividends', icon: Coins },
  { id: 'ipos', label: 'IPOs', icon: Rocket },
  { id: 'hours', label: 'Hours', icon: CalendarClock },
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

function EconomicView() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<any[][]>([])
  useEffect(() => {
    let alive = true
    apiClient
      .get('/macro/calendar', { days_ahead: 7 })
      .then((res: any) => {
        const events = (res?.data?.data as any[]) || []
        if (!alive) return
        setRows(
          events.map((e) => [
            e.date?.slice(0, 10) || '--',
            e.country || '--',
            e.event || '--',
            <span key="i" className={cn('px-1.5 py-0.5 rounded-full text-[10px]', impactBadge(e.impact))}>
              {e.impact || 'low'}
            </span>,
            e.estimate ?? '—',
            e.actual ?? '—',
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
      columns={['日期', '国家', '事件', '影响', '预期', '实际']}
      rows={rows}
      empty="暂无宏观经济事件"
    />
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
  const [tab, setTab] = useState<TabId>('markets')
  const [tz, setTz] = useState('Asia/Hong_Kong')
  const [snapshot, setSnapshot] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [last, setLast] = useState('')

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

  return (
    <div className="space-y-2.5 h-full flex flex-col">
      {/* 标题 + 时区切换 */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-primary" />
        <h1 className="text-base font-bold tracking-tight">全球市场日历</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          Calendars
        </span>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground ml-2" />}
        {last && (
          <div className="ml-auto flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground bg-secondary/50 border border-border/30 px-2 py-1 rounded">
            <Clock className="h-3 w-3" />
            <span>{last}</span>
          </div>
        )}
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

      {/* 顶部 Tab 栏（粘性） */}
      <div className="flex items-center gap-1 border-b border-border/30 overflow-x-auto scrollbar-thin">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors',
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
        {tab === 'markets' && <MarketsView snapshot={snapshot} />}
        {tab === 'economic' && <EconomicView />}
        {tab === 'earnings' && <EarningsView />}
        {tab === 'dividends' && <DividendsView />}
        {tab === 'ipos' && <IPOsView />}
        {tab === 'hours' && <HoursView />}
      </div>
    </div>
  )
}

export default CalendarsModule
