/**
 * COMM-01 / COMM-02 数据源健康度看板 + 贡献投票看板
 * - 健康卡片矩阵：名称 / 状态 / 延迟 / 今日调用量 / 成功率 / 限流次数
 * - 实时来源：GET /datasource/health-overview + WS /datasource/ws/health（STALE 推送）
 * - 投票看板：GET /datasource-vote/board + POST /datasource-vote/vote（每日每源限一票）
 */

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Clock,
  Database,
  Loader2,
  ThumbsUp,
} from 'lucide-react'
import { apiClient, API_BASE_URL, getValidAccessToken } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

type HealthStatus = 'healthy' | 'stale' | 'throttled' | 'error' | 'idle'

interface HealthCard {
  source: string
  status: HealthStatus
  connected: boolean
  latency_ms: number | null
  today_calls: number
  success_rate: number | null
  rate_limit_count: number
  last_request_ts: number | null
  last_success_ts: number | null
  is_throttled: boolean
  consecutive_rate_limits: number
  backoff_strategy: string | null
}

const STATUS_META: Record<
  HealthStatus,
  { label: string; cls: string; Icon: typeof CheckCircle2 }
> = {
  healthy: { label: '正常', cls: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10', Icon: CheckCircle2 },
  stale: { label: '失联', cls: 'text-red-400 border-red-500/40 bg-red-500/10', Icon: AlertTriangle },
  throttled: { label: '限流', cls: 'text-amber-400 border-amber-500/40 bg-amber-500/10', Icon: Clock },
  error: { label: '错误', cls: 'text-red-400 border-red-500/40 bg-red-500/10', Icon: AlertTriangle },
  idle: { label: '空闲', cls: 'text-slate-400 border-slate-500/30 bg-slate-500/10', Icon: CircleSlash },
}

function fmtTs(ts: number | null): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

export function DataSourceHealthModule() {
  const [cards, setCards] = useState<HealthCard[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState('')
  const [alerts, setAlerts] = useState<string[]>([])
  const [board, setBoard] = useState<any>(null)
  const [voting, setVoting] = useState(false)
  const { toast } = useToast()
  const wsRef = useRef<WebSocket | null>(null)

  const fetchOverview = async () => {
    try {
      const res = await apiClient.get('/datasource/health-overview')
      if (res.data?.sources) {
        setCards(res.data.sources)
        setLastUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      }
    } catch (e) {
      console.warn('[datasource-health] overview failed', e)
    } finally {
      setLoading(false)
    }
  }

  const fetchBoard = async () => {
    try {
      const res = await apiClient.get('/datasource-vote/board')
      if (res.data) setBoard(res.data)
    } catch (e) {
      console.warn('[datasource-vote] board failed', e)
    }
  }

  useEffect(() => {
    fetchOverview()
    fetchBoard()
    const id = setInterval(fetchOverview, 30000)
    return () => clearInterval(id)
  }, [])

  // WS 实时推送健康看板 + STALE 报警
  useEffect(() => {
    let isUnmounted = false
    let stopped = false
    const connect = async () => {
      if (stopped) return
      const token = await getValidAccessToken()
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const base =
        API_BASE_URL.startsWith('http')
          ? API_BASE_URL.replace(/^http/, 'ws')
          : `${protocol}//${window.location.host}${API_BASE_URL}`
      const wsUrl = `${base}/datasource/ws/health${token ? `?token=${token}` : ''}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'overview' && msg.sources) {
            setCards(msg.sources)
            setLastUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
          } else if (msg.type === 'alert') {
            setAlerts((prev) =>
              [`${new Date().toLocaleTimeString('zh-CN', { hour12: false })} ${msg.message}`, ...prev].slice(0, 5),
            )
            toast({ title: '⚠️ 数据源失联', description: msg.message })
          }
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        if (!isUnmounted && !stopped) setTimeout(connect, 5000)
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => {
      stopped = true
      isUnmounted = true
      wsRef.current?.close()
    }
  }, [toast])

  const vote = async (source: string) => {
    setVoting(true)
    try {
      const res = await apiClient.post('/datasource-vote/vote', { source })
      if (res.data?.ok) {
        toast({ title: '✅ 投票成功', description: `${source} 当前 ${res.data.votes} 票` })
        await fetchBoard()
      }
    } catch (e: any) {
      const detail = e?.data?.msg || e?.message || '投票失败'
      toast({ title: '❌ 投票失败', description: detail })
    } finally {
      setVoting(false)
    }
  }

  const myVotes: string[] = board?.my_votes_today || []

  const renderSection = (title: string, items: any[]) => (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-200">
        {title} <span className="text-slate-500">({items.length})</span>
      </h3>
      <div className="space-y-2">
        {items.map((it) => {
          const voted = myVotes.includes(it.name)
          return (
            <div
              key={it.name}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-100">{it.label || it.name}</div>
                <div className="truncate text-xs text-slate-500">{it.desc || it.name}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="rounded-md bg-indigo-500/15 px-2 py-1 text-xs font-semibold text-indigo-300">
                  {it.votes ?? 0} 票
                </span>
                <button
                  type="button"
                  disabled={voting || voted}
                  onClick={() => vote(it.name)}
                  className={cn(
                    'flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition',
                    voted
                      ? 'cursor-not-allowed bg-white/5 text-slate-500'
                      : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30',
                  )}
                >
                  <ThumbsUp className="h-3 w-3" />
                  {voted ? '已投' : '投票'}
                </button>
              </div>
            </div>
          )
        })}
        {items.length === 0 && <div className="text-xs text-slate-600">暂无</div>}
      </div>
    </div>
  )

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-indigo-400" />
          <h1 className="text-lg font-semibold text-slate-100">数据源健康度看板</h1>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
        </div>
        <div className="text-xs text-slate-500">
          最后更新：{lastUpdated || '—'} · 每 30s 轮询 + WS 实时推送
        </div>
      </div>

      {/* STALE 报警条 */}
      {alerts.length > 0 && (
        <div className="space-y-1 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
          {alerts.map((a, i) => (
            <div key={i} className="flex items-center gap-2">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              {a}
            </div>
          ))}
        </div>
      )}

      {/* 健康卡片矩阵 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {cards.map((c) => {
          const meta = STATUS_META[c.status]
          const Icon = meta.Icon
          return (
            <div
              key={c.source}
              className={cn(
                'rounded-xl border bg-white/5 p-4 transition',
                c.status === 'stale' || c.status === 'error'
                  ? 'border-red-500/40 shadow-[0_0_0_1px_rgba(239,68,68,0.2)]'
                  : 'border-white/10',
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-100">{c.source}</span>
                  {!c.connected && (
                    <span className="rounded bg-slate-500/20 px-1.5 py-0.5 text-[10px] text-slate-400">
                      未连接
                    </span>
                  )}
                </div>
                <span className={cn('flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs', meta.cls)}>
                  <Icon className="h-3 w-3" />
                  {meta.label}
                </span>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <Metric label="延迟" value={c.latency_ms ? `${c.latency_ms.toFixed(0)} ms` : '—'} />
                <Metric label="今日调用" value={String(c.today_calls)} />
                <Metric
                  label="成功率"
                  value={c.success_rate == null ? '—' : `${(c.success_rate * 100).toFixed(1)}%`}
                />
                <Metric label="限流次数" value={String(c.rate_limit_count)} />
              </div>

              <div className="mt-2 text-[10px] text-slate-500">
                最后请求 {fmtTs(c.last_request_ts)} · 最后成功 {fmtTs(c.last_success_ts)}
              </div>
            </div>
          )
        })}
        {!loading && cards.length === 0 && (
          <div className="col-span-full rounded-lg border border-white/10 bg-white/5 p-8 text-center text-sm text-slate-500">
            暂无已接入数据源
          </div>
        )}
      </div>

      {/* 投票看板 COMM-02 */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-slate-100">数据源贡献投票与需求看板</h2>
        <p className="mb-3 text-xs text-slate-500">
          每日每源限投一票，投票结果影响下一个数据源接入优先级。
        </p>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {renderSection('已接入', board?.connected || [])}
          {renderSection('开发中', board?.developing || [])}
          {renderSection('社区投票中', board?.voting || [])}
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-black/20 px-2 py-1.5">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="text-sm font-medium text-slate-200">{value}</div>
    </div>
  )
}
