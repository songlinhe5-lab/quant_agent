/**
 * 告警中心页面 (ALERT-04)
 * 布局对齐 docs/01 §10.2：左侧规则管理 + 右侧事件历史流
 */

import { useState, useEffect } from 'react'
import { Bell, Plus, CheckCheck, Activity } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAlertRules, useAlertEvents, useAlertEngineStatus } from '@/hooks/use-alert-api'
import { useAlertOverlayStore } from '@/stores/useAlertOverlayStore'
import type { CreateRulePayload } from '@/types/alert'
import { RulesList, EventsList } from './alert-lists'
import { CreateRuleForm } from './create-rule-form'

// ─── 主组件 ────────────────────────────────────────────────────────

export function AlertCenterModule() {
  const { rules, loading: rulesLoading, fetchRules, createRule, deleteRule, toggleRule } = useAlertRules()
  const { events, loading: eventsLoading, fetchEvents, ackEvent, ackAll } = useAlertEvents()
  const { status, fetchStatus } = useAlertEngineStatus()
  const wsStale = useAlertOverlayStore((s) => s.wsStale)
  const clearBadge = useAlertOverlayStore((s) => s.clearBadge)

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [prefillTicker, setPrefillTicker] = useState<string | undefined>()

  useEffect(() => {
    fetchRules()
    fetchEvents()
    fetchStatus()
    clearBadge()
  }, [fetchRules, fetchEvents, fetchStatus, clearBadge])

  useEffect(() => {
    if (!wsStale) fetchEvents()
  }, [wsStale, fetchEvents])

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
            <span data-testid="alert-history-stale" className="text-[10px] font-bold font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-500 border border-amber-500/30">
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
        <div className={cn(
          'flex-1 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden transition-opacity',
          wsStale && 'opacity-60 saturate-50',
        )}>
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

export default AlertCenterModule
