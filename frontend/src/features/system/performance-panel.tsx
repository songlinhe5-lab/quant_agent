'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Activity, AlertTriangle, RefreshCw, Timer, Server, Wifi,
  Database, Zap, Cpu, Network, ShieldCheck, ShieldAlert, ShieldOff,
  Globe, MonitorSmartphone,
} from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

// ─── 类型定义 ────────────────────────────────────────────────────────
interface HealthData {
  status: 'healthy' | 'degraded' | 'unhealthy'
  components: Record<string, string | Record<string, number>>
}

interface MetricsData {
  ws_connections: number
  ws_messages_sent: number
  ws_messages_dropped: number
  ws_subscriptions: number
  redis_queue_depth: Record<string, number>
  circuit_breaker_states: Record<string, number>
  market_quote_total: number
}

interface ClusterData {
  master?: { collectors: string[] }
  slaves?: Array<{ id: string; host: string; collectors: string[]; healthy: boolean }>
  pools?: Record<string, Array<{ id: string; healthy: boolean }>>
  error?: string
}

interface PerfStats {
  slow_request_count: number
  event_loop_block_count: number
  avg_duration_ms: number
  max_duration_ms: number
  total_count: number
}

interface PerfLog {
  id: number
  timestamp: string
  log_type: string
  duration_ms: number
  endpoint: string | null
  details: string | null
}

interface FrontendLog {
  id: number
  timestamp: string
  level: string
  message: string
  context: Record<string, any> | null
  page_url: string | null
  user_agent: string | null
}

// ─── 主组件 ──────────────────────────────────────────────────────────
export function PerformancePanel() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [metrics, setMetrics] = useState<MetricsData | null>(null)
  const [cluster, setCluster] = useState<ClusterData | null>(null)
  const [perfStats, setPerfStats] = useState<PerfStats | null>(null)
  const [logs, setLogs] = useState<PerfLog[]>([])
  const [logFilter, setLogFilter] = useState<string>('')
  const [loadingDash, setLoadingDash] = useState(true)
  const [loadingLogs, setLoadingLogs] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [frontendLogs, setFrontendLogs] = useState<FrontendLog[]>([])
  const [frontendLogFilter, setFrontendLogFilter] = useState<string>('')
  const [loadingFrontendLogs, setLoadingFrontendLogs] = useState(true)

  // 仪表盘聚合数据
  const fetchDashboard = useCallback(async () => {
    try {
      const res = await apiClient.get('/system/apm-dashboard') as any
      // apiClient 已解包 {code, data} → res.data = {status, data: {health, metrics, ...}}
      const d = res.data?.data
      if (d) {
        setHealth(d.health)
        setMetrics(d.metrics)
        setCluster(d.cluster)
        setPerfStats(d.performance_stats)
      }
    } catch (e) {
      console.error('APM dashboard fetch error:', e)
    } finally {
      setLoadingDash(false)
    }
  }, [])

  // 性能日志
  const fetchLogs = useCallback(async () => {
    try {
      const params: Record<string, any> = { limit: 200 }
      if (logFilter) params.log_type = logFilter
      const res = await apiClient.get('/system/performance-logs', params) as any
      if (res.data?.status === 'success') {
        setLogs(res.data.data)
      }
    } catch (e) {
      console.error('Performance logs fetch error:', e)
    } finally {
      setLoadingLogs(false)
    }
  }, [logFilter])

  // 前端日志
  const fetchFrontendLogs = useCallback(async () => {
    try {
      const params: Record<string, any> = { limit: 200 }
      if (frontendLogFilter) params.level = frontendLogFilter
      const res = await apiClient.get('/logs', params) as any
      if (res.data?.status === 'success') {
        setFrontendLogs(res.data.data?.items ?? [])
      }
    } catch (e) {
      console.error('Frontend logs fetch error:', e)
    } finally {
      setLoadingFrontendLogs(false)
    }
  }, [frontendLogFilter])

  // 初始加载 + 自动轮询
  useEffect(() => {
    fetchDashboard()
    fetchLogs()
    fetchFrontendLogs()
    const dashInterval = setInterval(fetchDashboard, 30000)
    const logInterval = setInterval(fetchLogs, 60000)
    const feLogInterval = setInterval(fetchFrontendLogs, 60000)
    return () => { clearInterval(dashInterval); clearInterval(logInterval); clearInterval(feLogInterval) }
  }, [fetchDashboard, fetchLogs, fetchFrontendLogs])

  const handleRefreshAll = async () => {
    setIsRefreshing(true)
    await Promise.all([fetchDashboard(), fetchLogs(), fetchFrontendLogs()])
    setTimeout(() => setIsRefreshing(false), 500)
  }

  return (
    <div className="space-y-4">
      {/* 标题栏 */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-slate-500 dark:bg-slate-400" />
        <h1 className="text-base font-bold tracking-tight">系统性能监控</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          System APM
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefreshAll}
          disabled={isRefreshing}
          className="ml-auto h-7 px-3 gap-1.5 text-[11px] bg-secondary/30 hover:bg-secondary/60 border-border/50"
        >
          <RefreshCw className={cn('h-3 w-3', isRefreshing && 'animate-spin')} />
          {isRefreshing ? '同步中' : '全量刷新'}
        </Button>
      </div>

      {/* [1] 系统健康概览 */}
      <HealthOverview data={health} loading={loadingDash} />

      {/* [2] 实时指标卡片 */}
      <MetricsCards data={metrics} stats={perfStats} loading={loadingDash} />

      {/* [3] 集群状态 */}
      <ClusterStatusPanel data={cluster} loading={loadingDash} />

      {/* [4] 性能异常追溯记录 */}
      <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm relative flex flex-col min-h-[400px] h-[calc(100vh-580px)]">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between bg-secondary/30 shrink-0">
          <div className="flex items-center gap-2">
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              性能异常追溯记录
              <span className="ml-2 bg-primary/10 text-primary px-1.5 py-0.5 rounded-md font-mono">{logs.length}</span>
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {['', 'slow_request', 'event_loop_block'].map((t) => (
              <button
                key={t}
                onClick={() => setLogFilter(t)}
                className={cn(
                  'text-[10px] px-2 py-0.5 rounded border transition-colors',
                  logFilter === t
                    ? 'bg-primary/15 text-primary border-primary/30'
                    : 'text-muted-foreground border-border/40 hover:bg-muted/50'
                )}
              >
                {t === '' ? '全部' : t === 'slow_request' ? '慢请求' : '事件循环阻塞'}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-auto flex-1 custom-scrollbar">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <tr className="border-b border-border/40">
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">时间</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">类型</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">触发节点</th>
                <th className="px-4 py-3 text-right text-muted-foreground font-medium whitespace-nowrap">耗时 (ms)</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium">详情</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/15">
              {loadingLogs ? (
                <tr><td colSpan={5} className="py-10 text-center text-muted-foreground"><RefreshCw className="h-5 w-5 animate-spin mx-auto mb-2 opacity-50" />加载中...</td></tr>
              ) : logs.length === 0 ? (
                <tr><td colSpan={5} className="py-10 text-center text-muted-foreground">当前系统极其健康，暂无任何慢请求或卡顿日志。</td></tr>
              ) : logs.map((log) => {
                const isBlock = log.log_type === 'event_loop_block'
                const typeColor = isBlock
                  ? 'text-[#e11d48] dark:text-[#f6465d] bg-[#f6465d]/10 border-[#f6465d]/20'
                  : 'text-amber-600 dark:text-amber-500 bg-amber-500/10 border-amber-500/20'
                const Icon = isBlock ? AlertTriangle : Timer
                return (
                  <tr key={log.id} className="hover:bg-muted/50 transition-colors group">
                    <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground whitespace-nowrap">{log.timestamp}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={cn('inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border', typeColor)}>
                        <Icon className="h-3 w-3" />
                        {isBlock ? '主循环阻塞' : '慢请求'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-foreground">{log.endpoint || '-'}</td>
                    <td className={cn('px-4 py-3 text-right font-mono font-bold tabular-nums', isBlock ? 'text-[#e11d48] dark:text-[#f6465d]' : 'text-amber-600 dark:text-amber-500')}>
                      {log.duration_ms.toFixed(1)}
                    </td>
                    <td className="px-4 py-3 text-[11px] text-muted-foreground leading-relaxed break-words max-w-md">
                      {log.details || '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* [5] 浏览器日志 (FE-05b) */}
      <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm relative flex flex-col min-h-[400px] h-[calc(100vh-580px)]">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between bg-secondary/30 shrink-0">
          <div className="flex items-center gap-2">
            <MonitorSmartphone className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              浏览器日志
              <span className="ml-2 bg-primary/10 text-primary px-1.5 py-0.5 rounded-md font-mono">{frontendLogs.length}</span>
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {['', 'ERROR', 'WARN', 'INFO', 'DEBUG'].map((t) => (
              <button
                key={t}
                onClick={() => setFrontendLogFilter(t)}
                className={cn(
                  'text-[10px] px-2 py-0.5 rounded border transition-colors',
                  frontendLogFilter === t
                    ? 'bg-primary/15 text-primary border-primary/30'
                    : 'text-muted-foreground border-border/40 hover:bg-muted/50'
                )}
              >
                {t === '' ? '全部' : t}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-auto flex-1 custom-scrollbar">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <tr className="border-b border-border/40">
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">时间</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">级别</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium">消息</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">页面</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/15">
              {loadingFrontendLogs ? (
                <tr><td colSpan={4} className="py-10 text-center text-muted-foreground"><RefreshCw className="h-5 w-5 animate-spin mx-auto mb-2 opacity-50" />加载中...</td></tr>
              ) : frontendLogs.length === 0 ? (
                <tr><td colSpan={4} className="py-10 text-center text-muted-foreground">暂无浏览器日志</td></tr>
              ) : frontendLogs.map((log) => {
                const levelColors: Record<string, string> = {
                  ERROR: 'text-[#e11d48] dark:text-[#f6465d] bg-[#f6465d]/10 border-[#f6465d]/20',
                  WARN: 'text-amber-600 dark:text-amber-500 bg-amber-500/10 border-amber-500/20',
                  INFO: 'text-blue-500 bg-blue-500/10 border-blue-500/20',
                  DEBUG: 'text-slate-500 bg-slate-500/10 border-slate-500/20',
                }
                const levelColor = levelColors[log.level] || levelColors.INFO
                return (
                  <tr key={log.id} className="hover:bg-muted/50 transition-colors group">
                    <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString('zh-CN', { hour12: false })}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={cn('inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border', levelColor)}>
                        {log.level}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[11px] text-foreground leading-relaxed break-words max-w-lg">
                      {log.message}
                      {log.context && (
                        <pre className="mt-1 text-[9px] text-muted-foreground bg-muted/30 rounded p-1 overflow-x-auto">
                          {JSON.stringify(log.context, null, 2)}
                        </pre>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-muted-foreground font-mono whitespace-nowrap max-w-[200px] truncate" title={log.page_url || ''}>
                      {log.page_url ? (() => { try { return new URL(log.page_url).pathname } catch { return log.page_url } })() : '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ─── [1] 系统健康概览 ─────────────────────────────────────────────────
function HealthOverview({ data, loading }: { data: HealthData | null; loading: boolean }) {
  const statusColor = (s: string) => {
    if (s === 'connected' || s === 'CONNECTED') return 'bg-emerald-500'
    if (s === 'degraded' || s?.startsWith('disconnected')) return 'bg-red-500'
    if (s === 'skipped' || s === 'idle' || s === 'unknown') return 'bg-amber-500'
    return 'bg-slate-400'
  }

  const overallBadge = (s: string) => {
    if (s === 'healthy') return { cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30', icon: ShieldCheck }
    if (s === 'degraded') return { cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30', icon: ShieldAlert }
    return { cls: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30', icon: ShieldOff }
  }

  if (loading) return <SectionSkeleton title="系统健康概览" />

  const badge = data ? overallBadge(data.status) : overallBadge('unhealthy')
  const BadgeIcon = badge.icon

  return (
    <div className="glass-card rounded-xl border border-border/40 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Server className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">系统健康概览</span>
        {data && (
          <span className={cn('ml-auto text-[10px] font-bold px-2 py-0.5 rounded border inline-flex items-center gap-1', badge.cls)}>
            <BadgeIcon className="h-3 w-3" />
            {data.status.toUpperCase()}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {data && Object.entries(data.components).map(([key, val]) => {
          const isObj = typeof val !== 'string'
          const label = isObj
            ? `workers:${(val as any).max_workers} idle:${(val as any).idle_workers ?? (val as any).spawned_threads} busy:${(val as any).busy_workers ?? (val as any).pending_tasks}`
            : val
          const statusVal = typeof val === 'string' ? val : ''
          return (
            <div key={key} className="flex items-center gap-2 text-xs bg-secondary/20 rounded-lg px-3 py-2">
              <div className={cn('h-2 w-2 rounded-full shrink-0', statusColor(statusVal))} />
              <div className="min-w-0">
                <div className="text-[10px] text-muted-foreground uppercase">{key}</div>
                <div className="font-mono text-[11px] truncate" title={label}>{label}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── [2] 实时指标卡片 ─────────────────────────────────────────────────
function MetricsCards({ data, stats, loading }: { data: MetricsData | null; stats: PerfStats | null; loading: boolean }) {
  if (loading) return <SectionSkeleton title="实时指标" />

  const cards = [
    { label: 'WS 连接数', value: data?.ws_connections ?? 0, icon: Wifi, color: 'text-blue-500' },
    { label: 'WS 消息发送', value: data?.ws_messages_sent ?? 0, icon: Network, color: 'text-emerald-500', format: formatNumber },
    { label: 'WS 消息丢弃', value: data?.ws_messages_dropped ?? 0, icon: Zap, color: 'text-red-500' },
    { label: 'WS 订阅数', value: data?.ws_subscriptions ?? 0, icon: Activity, color: 'text-purple-500' },
    { label: '行情总量', value: data?.market_quote_total ?? 0, icon: Database, color: 'text-cyan-500', format: formatNumber },
    { label: '慢请求 (24h)', value: stats?.slow_request_count ?? 0, icon: Timer, color: 'text-amber-500' },
    { label: '事件阻塞 (24h)', value: stats?.event_loop_block_count ?? 0, icon: AlertTriangle, color: 'text-rose-500' },
    { label: '最大耗时 (24h)', value: stats?.max_duration_ms ?? 0, icon: Cpu, color: 'text-orange-500', suffix: 'ms' },
  ]

  return (
    <div className="glass-card rounded-xl border border-border/40 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">实时指标</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-4 gap-3">
        {cards.map((c) => {
          const Icon = c.icon
          const display = c.format ? c.format(c.value) : c.value
          return (
            <div key={c.label} className="bg-secondary/20 rounded-lg px-3 py-2.5 flex items-center gap-3">
              <Icon className={cn('h-4 w-4 shrink-0', c.color)} />
              <div>
                <div className="text-[10px] text-muted-foreground">{c.label}</div>
                <div className="text-sm font-bold font-mono tabular-nums">
                  {display}{c.suffix ? <span className="text-[10px] text-muted-foreground ml-0.5">{c.suffix}</span> : null}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 熔断器状态 */}
      {data?.circuit_breaker_states && Object.keys(data.circuit_breaker_states).length > 0 && (
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <span className="text-[10px] text-muted-foreground">熔断器:</span>
          {Object.entries(data.circuit_breaker_states).map(([svc, state]) => (
            <span
              key={svc}
              className={cn(
                'text-[10px] font-mono px-1.5 py-0.5 rounded border',
                state === 0 ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' :
                state === 1 ? 'bg-amber-500/10 text-amber-500 border-amber-500/20' :
                'bg-red-500/10 text-red-500 border-red-500/20'
              )}
            >
              {svc}: {state === 0 ? 'CLOSED' : state === 1 ? 'HALF_OPEN' : 'OPEN'}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── [3] 集群状态 ─────────────────────────────────────────────────────
function ClusterStatusPanel({ data, loading }: { data: ClusterData | null; loading: boolean }) {
  if (loading) return <SectionSkeleton title="集群状态" />
  if (!data || data.error) {
    return (
      <div className="glass-card rounded-xl border border-border/40 p-4">
        <div className="flex items-center gap-2 mb-2">
          <Network className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">集群状态</span>
        </div>
        <p className="text-xs text-muted-foreground">集群信息不可用 {data?.error ? `: ${data.error}` : ''}</p>
      </div>
    )
  }

  const masterCollectors = data.master?.collectors ?? []
  const slaves = data.slaves ?? []
  const pools = data.pools ?? {}

  return (
    <div className="glass-card rounded-xl border border-border/40 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Network className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">集群状态</span>
        <span className="text-[10px] font-mono text-muted-foreground ml-auto">
          Master 采集器: {masterCollectors.length} | Slave 节点: {slaves.length}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Master 采集器 */}
        <div>
          <div className="text-[10px] text-muted-foreground mb-1.5 uppercase">Master 采集器</div>
          <div className="flex flex-wrap gap-1.5">
            {masterCollectors.length === 0 ? (
              <span className="text-[11px] text-muted-foreground">无</span>
            ) : masterCollectors.map((c) => (
              <span key={c} className="text-[10px] font-mono bg-blue-500/10 text-blue-500 border border-blue-500/20 px-1.5 py-0.5 rounded">{c}</span>
            ))}
          </div>
        </div>

        {/* Slave 节点 */}
        <div>
          <div className="text-[10px] text-muted-foreground mb-1.5 uppercase">Slave 节点</div>
          <div className="space-y-1">
            {slaves.length === 0 ? (
              <span className="text-[11px] text-muted-foreground">无从节点</span>
            ) : slaves.map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-[11px]">
                <div className={cn('h-1.5 w-1.5 rounded-full', s.healthy ? 'bg-emerald-500' : 'bg-red-500')} />
                <span className="font-mono">{s.id}</span>
                <span className="text-muted-foreground">{s.host}</span>
                <div className="flex gap-1 ml-auto">
                  {s.collectors?.map((c) => (
                    <span key={c} className="text-[9px] font-mono bg-secondary/50 px-1 py-0 rounded">{c}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 服务池 */}
      {Object.keys(pools).length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] text-muted-foreground mb-1.5 uppercase">服务池</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(pools).map(([collector, nodes]) => (
              <div key={collector} className="text-[10px] bg-secondary/20 rounded px-2 py-1">
                <span className="font-mono font-bold">{collector}</span>
                <span className="text-muted-foreground ml-1">({nodes.length} 节点)</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── 骨架屏 ──────────────────────────────────────────────────────────
function SectionSkeleton({ title }: { title: string }) {
  return (
    <div className="glass-card rounded-xl border border-border/40 p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="h-3.5 w-3.5 rounded bg-muted animate-pulse" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{title}</span>
      </div>
      <div className="grid grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-14 rounded-lg bg-muted/50 animate-pulse" />
        ))}
      </div>
    </div>
  )
}

// ─── 工具函数 ─────────────────────────────────────────────────────────
function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}
