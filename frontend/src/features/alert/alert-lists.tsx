/**
 * 告警规则列表 + 事件列表子组件
 */

import { useNavigate } from 'react-router-dom'
import { CheckCheck, Trash2, Play, Pause, AlertTriangle, Info, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import { applyAlertNavigation } from './alert-nav'
import type { AlertRule, AlertEvent, AlertRuleType } from '@/types/alert'
import { RULE_TYPE_LABELS, SEVERITY_COLORS } from '@/types/alert'

// ─── 规则列表 ──────────────────────────────────────────────────────

export function RulesList({ rules, onToggle, onDelete }: {
  rules: AlertRule[]
  onToggle: (ruleId: string) => Promise<unknown>
  onDelete: (ruleId: string) => Promise<void>
}) {
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
      <span className={cn('h-2 w-2 rounded-full shrink-0', rule.enabled ? SEVERITY_COLORS[rule.severity].replace('text-', 'bg-') : 'bg-slate-500')} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold truncate">{rule.name}</span>
          <span className="text-[10px] font-mono text-muted-foreground shrink-0">{rule.ticker}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-muted-foreground">阈值: {rule.threshold}</span>
          {rule.trigger_count > 0 && (
            <span className="text-[10px] text-muted-foreground">触发 {rule.trigger_count} 次</span>
          )}
        </div>
      </div>
      <span className={cn(
        'text-[9px] font-bold px-1.5 py-0.5 rounded',
        rule.enabled ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-slate-500/10 text-slate-500'
      )}>
        {rule.enabled ? '启用' : '停用'}
      </span>
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

export function EventsList({ events, onAck }: { events: AlertEvent[]; onAck: (eventId: string) => void }) {
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
            <span className="text-[10px] text-muted-foreground">触发值: {event.trigger_value.toFixed(2)}</span>
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
