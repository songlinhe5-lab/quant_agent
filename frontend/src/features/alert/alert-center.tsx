/**
 * 告警中心页面 (ALERT-04)
 * 布局对齐 docs/01 §10.2：左侧规则管理 + 右侧事件历史流
 */

import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Plus, CheckCheck, Trash2, Play, Pause, X, Activity, AlertTriangle, Info, Zap, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAlertRules, useAlertEvents, useAlertEngineStatus } from '@/hooks/use-alert-api'
import { useAlertOverlayStore } from '@/stores/useAlertOverlayStore'
import { applyAlertNavigation } from './alert-nav'
import type { AlertRule, AlertEvent, AlertRuleType, AlertSeverity, AlertChannel, CreateRulePayload } from '@/types/alert'
import { RULE_TYPE_LABELS, SEVERITY_LABELS, SEVERITY_COLORS } from '@/types/alert'

// ─── 主组件 ────────────────────────────────────────────────────────

export function AlertCenterModule() {
  const { rules, loading: rulesLoading, fetchRules, createRule, deleteRule, toggleRule } = useAlertRules()
  const { events, loading: eventsLoading, fetchEvents, ackEvent, ackAll } = useAlertEvents()
  const { status, fetchStatus } = useAlertEngineStatus()
  const wsStale = useAlertOverlayStore((s) => s.wsStale)
  const clearBadge = useAlertOverlayStore((s) => s.clearBadge)

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [prefillTicker, setPrefillTicker] = useState<string | undefined>()

  // 初始加载（实时推送由 GlobalAlertGateway 常驻；本页轮询/聚焦刷新）
  useEffect(() => {
    fetchRules()
    fetchEvents()
    fetchStatus()
    clearBadge()
  }, [fetchRules, fetchEvents, fetchStatus, clearBadge])

  // WS 重连后补拉（stale→false）
  useEffect(() => {
    if (!wsStale) {
      fetchEvents()
    }
  }, [wsStale, fetchEvents])

  // 监听全局"设置价格告警"事件（从行情页右键菜单触发）
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.ticker) {
        setPrefillTicker(detail.ticker)
        setShowCreateForm(true)
      }
    }
    window.addEventListener('open-alert-create', handler)
    return () => window.removeEventListener('open-alert-create', handler)
  }, [])

  const handleCreate = async (payload: CreateRulePayload) => {
    const rule = await createRule(payload)
    if (rule) {
      setShowCreateForm(false)
      setPrefillTicker(undefined)
    }
  }

  const handleDelete = async (ruleId: string) => {
    if (confirm('确定删除此告警规则？')) {
      await deleteRule(ruleId)
    }
  }

  const unreadCount = events.filter(e => !e.acknowledged).length

  return (
    <div className="h-[calc(100vh-80px)] min-h-[600px] w-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between px-1 shrink-0">
        <div className="flex items-center gap-3">
          <Bell className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-bold">告警中心</h1>
          {wsStale && (
            <span
              data-testid="alert-history-stale"
              className="text-[10px] font-bold font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-500 border border-amber-500/30"
            >
              STALE
            </span>
          )}
          {status && (
            <span className={cn(
              'flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full',
              status.running ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/10 text-red-500'
            )}>
              <span className={cn('h-1.5 w-1.5 rounded-full', status.running ? 'bg-emerald-500 animate-pulse' : 'bg-red-500')} />
              {status.running ? '引擎运行中' : '引擎停止'}
            </span>
          )}
          {status && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {status.active_rules} 条活跃规则 · {status.trigger_count} 次触发
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => { ackAll() }} disabled={unreadCount === 0} className="h-7 text-xs">
            <CheckCheck className="h-3.5 w-3.5 mr-1" /> 全部已读
          </Button>
          <Button size="sm" onClick={() => { setPrefillTicker(undefined); setShowCreateForm(true) }} className="h-7 text-xs">
            <Plus className="h-3.5 w-3.5 mr-1" /> 新建告警
          </Button>
        </div>
      </div>

      {/* Main Content: Two-Panel Layout */}
      <div className="flex-1 flex gap-3 min-h-0">
        {/* Left Panel: Rules */}
        <div className="w-[380px] shrink-0 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0">
            <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">告警规则管理</span>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {rulesLoading ? (
              <div className="flex items-center justify-center h-32">
                <div className="h-5 w-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            ) : rules.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
                <Bell className="h-8 w-8 mb-2 opacity-30" />
                <p className="text-xs">暂无告警规则</p>
                <p className="text-[10px] mt-1">点击"新建告警"创建第一条规则</p>
              </div>
            ) : (
              <RulesList rules={rules} onToggle={toggleRule} onDelete={handleDelete} />
            )}
          </div>
        </div>

        {/* Right Panel: Events */}
        <div
          className={cn(
            'flex-1 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden transition-opacity',
            wsStale && 'opacity-60 saturate-50',
          )}
        >
          <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0 flex items-center justify-between">
            <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-2">
              告警历史
              {wsStale && <span className="text-amber-500 normal-case tracking-normal">STALE · 推送已断</span>}
            </span>
            {unreadCount > 0 && (
              <span className="text-[10px] font-mono text-amber-500">{unreadCount} 条未读</span>
            )}
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {eventsLoading ? (
              <div className="flex items-center justify-center h-32">
                <div className="h-5 w-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            ) : events.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
                <Activity className="h-8 w-8 mb-2 opacity-30" />
                <p className="text-xs">暂无告警事件</p>
              </div>
            ) : (
              <EventsList events={events} onAck={ackEvent} />
            )}
          </div>
        </div>
      </div>

      {/* Create Form Modal */}
      {showCreateForm && (
        <CreateRuleForm
          prefillTicker={prefillTicker}
          onSubmit={handleCreate}
          onClose={() => { setShowCreateForm(false); setPrefillTicker(undefined) }}
        />
      )}
    </div>
  )
}

// ─── 规则列表 ──────────────────────────────────────────────────────

function RulesList({ rules, onToggle, onDelete }: {
  rules: AlertRule[]
  onToggle: (ruleId: string) => Promise<unknown>
  onDelete: (ruleId: string) => Promise<void>
}) {
  // 按类型分组
  const grouped = rules.reduce<Record<string, AlertRule[]>>((acc, rule) => {
    const key = rule.rule_type
    if (!acc[key]) acc[key] = []
    acc[key].push(rule)
    return acc
  }, {})

  return (
    <div className="divide-y divide-border/20">
      {Object.entries(grouped).map(([type, typeRules]) => (
        <div key={type}>
          <div className="px-4 py-2 bg-secondary/10">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
              {RULE_TYPE_LABELS[type as AlertRuleType] || type}
            </span>
          </div>
          {typeRules.map(rule => (
            <RuleItem key={rule.rule_id} rule={rule} onToggle={() => onToggle(rule.rule_id)} onDelete={() => onDelete(rule.rule_id)} />
          ))}
        </div>
      ))}
    </div>
  )
}

function RuleItem({ rule, onToggle, onDelete }: { rule: AlertRule; onToggle: () => void; onDelete: () => void }) {
  return (
    <div className={cn(
      'flex items-center gap-3 px-4 py-2.5 border-b border-border/10 hover:bg-secondary/30 transition-colors',
      !rule.enabled && 'opacity-50'
    )}>
      {/* Severity dot */}
      <span className={cn('h-2 w-2 rounded-full shrink-0', rule.enabled ? SEVERITY_COLORS[rule.severity].replace('text-', 'bg-') : 'bg-slate-500')} />

      {/* Rule info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold truncate">{rule.name}</span>
          <span className="text-[10px] font-mono text-muted-foreground shrink-0">{rule.ticker}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-muted-foreground">
            阈值: {rule.threshold}
          </span>
          {rule.trigger_count > 0 && (
            <span className="text-[10px] text-muted-foreground">
              触发 {rule.trigger_count} 次
            </span>
          )}
        </div>
      </div>

      {/* Status badge */}
      <span className={cn(
        'text-[9px] font-bold px-1.5 py-0.5 rounded',
        rule.enabled ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-slate-500/10 text-slate-500'
      )}>
        {rule.enabled ? '启用' : '停用'}
      </span>

      {/* Actions */}
      <div className="flex items-center gap-1">
        <button onClick={onToggle} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground hover:text-foreground transition-colors" title={rule.enabled ? '停用' : '启用'}>
          {rule.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </button>
        <button onClick={onDelete} className="p-1 rounded hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-colors" title="删除">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

// ─── 事件列表 ──────────────────────────────────────────────────────

function EventsList({ events, onAck }: { events: AlertEvent[]; onAck: (eventId: string) => void }) {
  return (
    <div className="divide-y divide-border/10">
      {events.map(event => (
        <EventItem key={event.event_id} event={event} onAck={() => onAck(event.event_id)} />
      ))}
    </div>
  )
}

function EventItem({ event, onAck }: { event: AlertEvent; onAck: () => void }) {
  const navigate = useNavigate()
  const time = new Date(event.triggered_at * 1000)
  const timeStr = time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const dateStr = time.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })

  const severityIcon = event.severity === 'critical' ? <AlertTriangle className="h-3.5 w-3.5 text-red-500" /> :
    event.severity === 'warning' ? <AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> :
    <Info className="h-3.5 w-3.5 text-blue-500" />

  return (
    <div className={cn(
      'flex items-start gap-3 px-4 py-3 hover:bg-secondary/20 transition-colors',
      !event.acknowledged && 'bg-primary/[0.03]'
    )}>
      {severityIcon}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold">{event.message}</span>
          {!event.acknowledged && (
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
          )}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10px] font-mono text-muted-foreground">{event.ticker}</span>
          {event.trigger_value !== null && (
            <span className="text-[10px] text-muted-foreground">
              触发值: {event.trigger_value.toFixed(2)}
            </span>
          )}
          <span className="text-[10px] text-muted-foreground">{dateStr} {timeStr}</span>
          {event.priority && (
            <span className={cn('text-[9px] font-bold px-1 py-0 rounded', event.priority === 'p0' ? 'bg-red-500/10 text-red-500' : event.priority === 'p1' ? 'bg-amber-500/10 text-amber-500' : 'text-slate-500')}>
              {event.priority.toUpperCase()}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {(event.ticker || event.ui_hint?.symbol || event.ui_hint?.route) && (
          <button
            type="button"
            onClick={() => applyAlertNavigation(navigate, event.ui_hint, event.ticker)}
            className="p-1 rounded hover:bg-sky-500/10 text-muted-foreground hover:text-sky-400 transition-colors"
            title="查看行情"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
        )}
        {!event.acknowledged && (
          <button onClick={onAck} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground hover:text-foreground transition-colors" title="标记已读">
            <CheckCheck className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

// ─── 新建规则表单（Modal）──────────────────────────────────────────

function CreateRuleForm({ prefillTicker, onSubmit, onClose }: {
  prefillTicker?: string
  onSubmit: (payload: CreateRulePayload) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [ticker, setTicker] = useState(prefillTicker || '')
  const [ruleType, setRuleType] = useState<AlertRuleType>('price_above')
  const [threshold, setThreshold] = useState('')
  const [severity, setSeverity] = useState<AlertSeverity>('warning')
  const [channels, setChannels] = useState<AlertChannel[]>(['in_app'])
  const [cooldown, setCooldown] = useState(300)
  const [submitting, setSubmitting] = useState(false)
  // ALERT-05: 指标类规则额外字段
  const [direction, setDirection] = useState<'golden' | 'death'>('golden')
  const [shortPeriod, setShortPeriod] = useState(10)
  const [longPeriod, setLongPeriod] = useState(20)

  const isIndicatorRule = ['rsi_threshold', 'macd_cross', 'ma_cross'].includes(ruleType)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !ticker) return

    // 指标类规则 threshold 可为空（MA_CROSS 不需要）
    if (!isIndicatorRule && !threshold) return

    setSubmitting(true)

    // 构建 metadata
    const metadata: Record<string, unknown> = {}
    if (ruleType === 'macd_cross') {
      metadata.direction = direction
    } else if (ruleType === 'ma_cross') {
      metadata.direction = direction
      metadata.short_period = shortPeriod
      metadata.long_period = longPeriod
    }

    await onSubmit({
      name,
      ticker: ticker.toUpperCase(),
      rule_type: ruleType,
      threshold: threshold ? parseFloat(threshold) : 0,
      severity,
      channels,
      cooldown_seconds: cooldown,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    })
    setSubmitting(false)
  }

  const toggleChannel = (ch: AlertChannel) => {
    setChannels(prev => prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div className="w-[440px] bg-background border border-border/60 rounded-xl shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/40">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-bold">新建告警规则</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground"><X className="h-4 w-4" /></button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">规则名称</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="如: AAPL 突破 $200"
              className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50"
              required
            />
          </div>

          {/* Ticker + Type */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">标的代码</label>
              <input
                type="text"
                value={ticker}
                onChange={e => setTicker(e.target.value)}
                placeholder="AAPL / 00700.HK"
                className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
                required
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">告警类型</label>
              <select
                value={ruleType}
                onChange={e => setRuleType(e.target.value as AlertRuleType)}
                className="w-full h-8 px-2 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50"
              >
                {Object.entries(RULE_TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Threshold / 指标参数 */}
          {ruleType === 'rsi_threshold' && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">RSI 阈值</label>
              <input
                type="number"
                step="1"
                min="1"
                max="99"
                value={threshold}
                onChange={e => setThreshold(e.target.value)}
                placeholder="30 = 超卖告警, 70 = 超买告警"
                className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
                required
              />
              <p className="text-[10px] text-muted-foreground mt-1">≤50 触发 RSI 低于阈值（超卖），&gt;50 触发 RSI 高于阈值（超买）</p>
            </div>
          )}

          {ruleType === 'macd_cross' && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">穿越方向</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setDirection('golden')}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors',
                    direction === 'golden' ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-600' : 'bg-secondary/20 border-border/50 text-muted-foreground'
                  )}
                >
                  🟢 金叉（MACD 上穿 Signal）
                </button>
                <button
                  type="button"
                  onClick={() => setDirection('death')}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors',
                    direction === 'death' ? 'bg-red-500/10 border-red-500/50 text-red-600' : 'bg-secondary/20 border-border/50 text-muted-foreground'
                  )}
                >
                  🔴 死叉（MACD 下穿 Signal）
                </button>
              </div>
            </div>
          )}

          {ruleType === 'ma_cross' && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">短期均线周期</label>
                  <input
                    type="number"
                    value={shortPeriod}
                    onChange={e => setShortPeriod(parseInt(e.target.value) || 10)}
                    min="2"
                    max="200"
                    className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">长期均线周期</label>
                  <input
                    type="number"
                    value={longPeriod}
                    onChange={e => setLongPeriod(parseInt(e.target.value) || 20)}
                    min="2"
                    max="200"
                    className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
                  />
                </div>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">穿越方向</label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setDirection('golden')}
                    className={cn(
                      'px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors',
                      direction === 'golden' ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-600' : 'bg-secondary/20 border-border/50 text-muted-foreground'
                    )}
                  >
                    🟢 金叉（短均上穿长均）
                  </button>
                  <button
                    type="button"
                    onClick={() => setDirection('death')}
                    className={cn(
                      'px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors',
                      direction === 'death' ? 'bg-red-500/10 border-red-500/50 text-red-600' : 'bg-secondary/20 border-border/50 text-muted-foreground'
                    )}
                  >
                    🔴 死叉（短均下穿长均）
                  </button>
                </div>
              </div>
            </div>
          )}

          {!isIndicatorRule && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">阈值</label>
              <input
                type="number"
                step="any"
                value={threshold}
                onChange={e => setThreshold(e.target.value)}
                placeholder="触发价格或指标值"
                className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
                required
              />
            </div>
          )}

          {/* Severity + Cooldown */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">严重级别</label>
              <select
                value={severity}
                onChange={e => setSeverity(e.target.value as AlertSeverity)}
                className="w-full h-8 px-2 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50"
              >
                {Object.entries(SEVERITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">冷却时间 (秒)</label>
              <input
                type="number"
                value={cooldown}
                onChange={e => setCooldown(parseInt(e.target.value) || 300)}
                min={60}
                className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50"
              />
            </div>
          </div>

          {/* Channels */}
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground mb-1.5 block">推送通道</label>
            <div className="flex gap-2">
              {(['in_app', 'feishu', 'telegram'] as AlertChannel[]).map(ch => (
                <button
                  key={ch}
                  type="button"
                  onClick={() => toggleChannel(ch)}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors',
                    channels.includes(ch)
                      ? 'bg-primary/10 border-primary/50 text-primary'
                      : 'bg-secondary/20 border-border/50 text-muted-foreground hover:border-primary/30'
                  )}
                >
                  {ch === 'in_app' ? '应用内' : ch === 'feishu' ? '飞书' : 'Telegram'}
                </button>
              ))}
            </div>
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose} className="h-8 text-xs">取消</Button>
            <Button type="submit" size="sm" disabled={submitting || !name || !ticker || (!isIndicatorRule && !threshold)} className="h-8 text-xs">
              {submitting ? '创建中...' : '创建规则'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default AlertCenterModule
