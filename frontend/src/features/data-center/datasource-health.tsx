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
  Plug,
  ThumbsUp,
} from 'lucide-react'
import { apiClient, getValidAccessToken, getWsBaseUrl } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

type HealthStatus = 'healthy' | 'stale' | 'throttled' | 'error' | 'idle' | 'blocked' | 'quota_exhausted'

interface HealthCard {
  source: string
  status: HealthStatus
  connected: boolean
  latency_ms: number | null
  today_calls: number
  success_rate: number | null
  rate_limit_count: number
  rl_category?: string | null
  rl_breakdown?: Record<string, number>
  last_request_ts: number | null
  last_success_ts: number | null
  is_throttled: boolean
  consecutive_rate_limits: number
  backoff_strategy: string | null
  latency_avg_ms?: number | null
  latency_p95_ms?: number | null
  latency_min_ms?: number | null
  latency_max_ms?: number | null
  latency_samples?: number
}

interface LinkTestResult {
  source: string
  connected: boolean
  healthy: boolean
  status: string
  latency_ms: number
  probed: boolean
  validated: boolean
  error: string | null
  tested_at: string
}

// YFinance 主/备节点（DIST-SEC-06）：DataSourceRouter 节点级健康状态
interface RouterNode {
  name: string
  role: 'primary' | 'backup'
  url: string
  enabled: boolean
  weight: number
  status: string
  capabilities: string[]
  error_count: number
  cooldown_remaining: number
  action_breakers: Record<string, number>
  action_error_counts: Record<string, number>
  is_throttled: boolean
  consecutive_rate_limits: number
  total_rate_limits_1h: number
  estimated_limit_rpm: number | null
  backoff_strategy: string | null
}

const STATUS_META: Record<
  HealthStatus,
  { label: string; cls: string; Icon: typeof CheckCircle2 }
> = {
  healthy: { label: '正常', cls: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10', Icon: CheckCircle2 },
  stale: { label: '失联', cls: 'text-red-400 border-red-500/40 bg-red-500/10', Icon: AlertTriangle },
  throttled: { label: '限流', cls: 'text-amber-400 border-amber-500/40 bg-amber-500/10', Icon: Clock },
  blocked: { label: 'IP封禁', cls: 'text-orange-400 border-orange-500/40 bg-orange-500/10', Icon: CircleSlash },
  quota_exhausted: { label: '额度耗尽', cls: 'text-purple-400 border-purple-500/40 bg-purple-500/10', Icon: Clock },
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
  const [testStates, setTestStates] = useState<Record<string, { testing: boolean; result?: LinkTestResult | null; error?: string }>>({})
  // 「全部测试连接」进行中全局锁：过程中禁用所有按钮，禁止并发堆积触发
  const [testingAll, setTestingAll] = useState(false)
  // YFinance 主/备节点健康（DIST-SEC-06）
  const [routerEnabled, setRouterEnabled] = useState(false)
  const [routerNodes, setRouterNodes] = useState<RouterNode[]>([])
  const { toast } = useToast()
  const wsRef = useRef<WebSocket | null>(null)

  const fetchRouterHealth = async () => {
    try {
      const res = await apiClient.get('/datasource/router/health')
      if (res.data?.yfinance?.nodes) {
        setRouterEnabled(res.data.router_enabled)
        setRouterNodes(res.data.yfinance.nodes)
      }
    } catch (e) {
      console.warn('[datasource-health] router health failed', e)
    }
  }

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
    fetchRouterHealth()
    const id = setInterval(fetchOverview, 30000)
    const rid = setInterval(fetchRouterHealth, 15000)
    return () => {
      clearInterval(id)
      clearInterval(rid)
    }
  }, [])

  // WS 实时推送健康看板 + STALE 报警
  useEffect(() => {
    let isUnmounted = false
    let stopped = false
    const connect = async () => {
      if (stopped) return
      const token = await getValidAccessToken()
      const wsUrl = `${getWsBaseUrl()}/datasource/ws/health${token ? `?token=${token}` : ''}`
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

  const testLink = async (source: string) => {
    // 「全部测试连接」进行中，禁止单独触发，避免与全局任务并发堆积
    if (testingAll) return
    setTestStates((prev) => ({ ...prev, [source]: { ...prev[source], testing: true, error: undefined } }))
    try {
      const res = await apiClient.post<LinkTestResult>(`/datasource/${source}/test-link`)
      const data = (res as unknown as { data: LinkTestResult }).data
      setTestStates((prev) => ({ ...prev, [source]: { testing: false, result: data } }))
      toast({
        title: data.connected ? '✅ 链路正常' : '❌ 链路异常',
        description: `${source} · ${data.latency_ms.toFixed(0)}ms${data.probed ? ' · 已主动探测' : ' · 被动探测'}`,
      })
    } catch (e: any) {
      const detail = e?.response?.data?.msg || e?.message || '链路测试失败'
      setTestStates((prev) => ({ ...prev, [source]: { testing: false, error: detail } }))
      toast({ title: '❌ 链路测试失败', description: detail })
    }
  }

  const testAll = async () => {
    if (testingAll) return
    setTestingAll(true)
    try {
      // 串行触发，避免瞬间并发风暴打爆上游；每个源完成后再进入下一个
      for (const c of cards) {
        await testLink(c.source)
      }
    } finally {
      setTestingAll(false)
    }
  }

  const renderSection = (title: string, items: any[]) => (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-semibold text-foreground">
        {title} <span className="text-muted-foreground">({items.length})</span>
      </h3>
      <div className="space-y-2">
        {items.map((it) => {
          const voted = myVotes.includes(it.name)
          return (
            <div
              key={it.name}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground">{it.label || it.name}</div>
                <div className="truncate text-xs text-muted-foreground">{it.desc || it.name}</div>
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
                      ? 'cursor-not-allowed bg-card text-muted-foreground'
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
        {items.length === 0 && <div className="text-xs text-muted-foreground">暂无</div>}
      </div>
    </div>
  )

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-indigo-400" />
          <h1 className="text-lg font-semibold text-foreground">数据源健康度看板</h1>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={cards.length === 0 || testingAll}
            onClick={testAll}
            className="flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {testingAll ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
            {testingAll ? '全部测试中…' : '全部测试连接'}
          </button>
          <div className="text-xs text-muted-foreground">
            最后更新：{lastUpdated || '—'} · 每 30s 轮询 + WS 实时推送
          </div>
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
          const t = testStates[c.source]
          return (
            <div
              key={c.source}
              className={cn(
                'rounded-xl border bg-card p-4 transition',
                c.status === 'stale' || c.status === 'error'
                  ? 'border-red-500/40 shadow-[0_0_0_1px_rgba(239,68,68,0.2)]'
                  : 'border-border',
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">{c.source}</span>
                  {!c.connected && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
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
                <div className="rounded-md bg-muted/40 px-2 py-1.5">
                  <div className="text-[10px] text-muted-foreground">调用延迟</div>
                  <div className="text-sm font-medium text-foreground">
                    {/* 当无延迟数据时显示 N/A，而非 0ms */}
                    {c.latency_ms != null && c.latency_ms > 0
                      ? `${c.latency_ms.toFixed(0)} ms`
                      : 'N/A'}
                  </div>
                  {c.latency_samples && c.latency_samples > 0 ? (
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[10px] text-muted-foreground">
                      <span>均值 {c.latency_avg_ms != null && c.latency_avg_ms > 0 ? c.latency_avg_ms.toFixed(0) : '—'}</span>
                      <span>· P95 {c.latency_p95_ms != null && c.latency_p95_ms > 0 ? c.latency_p95_ms.toFixed(0) : '—'}</span>
                      <span>· n={c.latency_samples}</span>
                      <span className="inline-flex items-center gap-0.5 text-emerald-400">
                        <CheckCircle2 className="h-2.5 w-2.5" />Redis 持久化
                      </span>
                    </div>
                  ) : (
                    <div className="mt-0.5 text-[10px] text-amber-400/80">暂无延迟数据（等待业务调用）</div>
                  )}
                </div>
                <Metric label="今日调用" value={String(c.today_calls)} />
                <Metric
                  label="成功率"
                  value={c.success_rate == null ? '—' : `${(c.success_rate * 100).toFixed(1)}%`}
                />
                <Metric label="限流次数" value={String(c.rate_limit_count)} />
              </div>

              {c.rl_breakdown && Object.keys(c.rl_breakdown).length > 0 && (
                <div className="mt-1 flex flex-wrap gap-x-2 text-[10px] text-muted-foreground">
                  {Object.entries(c.rl_breakdown).map(([k, v]) => (
                    <span
                      key={k}
                      className={cn(
                        k === 'ip_blocked' && 'text-orange-400',
                        k === 'quota_exhausted' && 'text-purple-400',
                        k === 'rate_limit' && 'text-amber-400',
                      )}
                    >
                      {k === 'rate_limit' ? '限流' : k === 'ip_blocked' ? 'IP封禁' : k === 'quota_exhausted' ? '配额耗尽' : k}{' '}
                      {v}
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-2 flex items-center justify-between gap-2">
                <button
                  type="button"
                  disabled={t?.testing || testingAll}
                  onClick={() => testLink(c.source)}
                  className="flex items-center gap-1 rounded-md bg-primary/15 px-2 py-1 text-[11px] font-medium text-primary transition hover:bg-primary/25 disabled:opacity-60"
                >
                  {t?.testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plug className="h-3 w-3" />}
                  {t?.testing ? '测试中' : '测试连接'}
                </button>
                {t?.result && (
                  <span className={cn('text-[10px]', t.result.connected ? 'text-emerald-400' : 'text-red-400')}>
                    {t.result.latency_ms.toFixed(0)}ms{t.result.probed ? ' · 实测' : ' · 被动'}
                  </span>
                )}
                {t?.error && <span className="text-[10px] text-red-400">{t.error}</span>}
              </div>

              <div className="mt-2 text-[10px] text-muted-foreground">
                最后请求 {fmtTs(c.last_request_ts)} · 最后成功 {fmtTs(c.last_success_ts)}
              </div>
            </div>
          )
        })}
        {!loading && cards.length === 0 && (
          <div className="col-span-full rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            暂无已接入数据源
          </div>
        )}
      </div>

      {/* YFinance 主/备节点健康度（DIST-SEC-06）：逐个展示 yf_primary / yf_backup_N 状态 */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground">
            YFinance 主/备数据源节点
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {routerEnabled ? (
                <span className="text-emerald-400">路由已启用</span>
              ) : (
                <span className="text-amber-400">路由未启用（本地兜底）</span>
              )}
            </span>
          </h2>
          <span className="text-xs text-muted-foreground">
            主 {routerNodes.filter((n) => n.role === 'primary').length} · 备{' '}
            {routerNodes.filter((n) => n.role === 'backup').length} · 每 15s 轮询
          </span>
        </div>

        {!routerEnabled && (
          <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            数据源路由未启用，以下节点状态仅供参考（实际走本地兜底，无远程节点）。
          </div>
        )}

        {routerNodes.length === 0 ? (
          <div className="rounded-md border border-border bg-muted/40 px-3 py-6 text-center text-sm text-muted-foreground">
            暂无 YFinance 节点（路由未配置主/备地址）
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {routerNodes.map((n) => {
              const isDegraded =
                n.status !== 'healthy' || n.is_throttled || n.cooldown_remaining > 0
              const effectiveStatus: HealthStatus = n.is_throttled
                ? 'throttled'
                : n.status === 'healthy'
                  ? 'healthy'
                  : 'error'
              const meta = STATUS_META[effectiveStatus]
              const Icon = meta.Icon
              return (
                <div
                  key={n.name}
                  className={cn(
                    'rounded-xl border bg-card p-4 transition',
                    isDegraded ? 'border-red-500/40 shadow-[0_0_0_1px_rgba(239,68,68,0.2)]' : 'border-border',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">{n.name}</span>
                      <span
                        className={cn(
                          'rounded px-1.5 py-0.5 text-[10px] font-medium',
                          n.role === 'primary'
                            ? 'bg-indigo-500/20 text-indigo-300'
                            : 'bg-slate-500/20 text-slate-300',
                        )}
                      >
                        {n.role === 'primary' ? '主节点' : '备节点'}
                      </span>
                    </div>
                    <span className={cn('flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs', meta.cls)}>
                      <Icon className="h-3 w-3" />
                      {meta.label}
                    </span>
                  </div>

                  <div className="mt-1 truncate text-[10px] text-muted-foreground" title={n.url}>
                    {n.url}
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <Metric
                      label="熔断冷却"
                      value={n.cooldown_remaining > 0 ? `${n.cooldown_remaining}s` : '—'}
                    />
                    <Metric label="连续限流" value={String(n.consecutive_rate_limits)} />
                    <Metric label="错误计数" value={String(n.error_count)} />
                    <Metric
                      label="退避策略"
                      value={n.backoff_strategy ? n.backoff_strategy.replace('_', ' ') : '—'}
                    />
                  </div>

                  {n.action_breakers && Object.keys(n.action_breakers).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-x-2 text-[10px]">
                      <span className="text-amber-400">Action 熔断:</span>
                      {Object.entries(n.action_breakers).map(([act, sec]) => (
                        <span key={act} className="rounded bg-amber-500/10 px-1 text-amber-300">
                          {act} {sec}s
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-2 text-[10px] text-muted-foreground">
                    {n.is_throttled ? (
                      <span className="text-amber-400">⏳ 退避中（雅虎熔断保护）</span>
                    ) : n.total_rate_limits_1h > 0 ? (
                      <span>近 1h 限流 {n.total_rate_limits_1h} 次 · 估 RPM {n.estimated_limit_rpm ?? '—'}</span>
                    ) : (
                      <span>近 1h 无限流 · 估 RPM {n.estimated_limit_rpm ?? '—'}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 投票看板 COMM-02 */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-foreground">数据源贡献投票与需求看板</h2>
        <p className="mb-3 text-xs text-muted-foreground">
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
    <div className="rounded-md bg-muted/40 px-2 py-1.5">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="text-sm font-medium text-foreground">{value}</div>
    </div>
  )
}
