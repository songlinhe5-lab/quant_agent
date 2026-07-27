import React, { useEffect, useRef, useState, useCallback } from 'react'
import { Bell, BellRing, Plus, Trash2, Power, Pencil, Play, X, Check, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import type { CIBar } from './engine'
import {
  useAlertSandboxStore,
  evalCondition,
  type AlertCondition,
  type AlertNotifyMode,
  type ConditionEvalResult,
} from './alert-sandbox'

interface Props {
  open: boolean
  onClose: () => void
  getBars: () => CIBar[]
}

interface Template {
  label: string
  expr: string
}

const TEMPLATES: Template[] = [
  { label: 'RSI 超买 ( > 70 )', expr: 'RSI(14) > 70' },
  { label: 'RSI 超卖 ( < 30 )', expr: 'RSI(14) < 30' },
  { label: '站上 MA20', expr: 'CLOSE > MA(CLOSE, 20)' },
  { label: '跌破 MA20', expr: 'CLOSE < MA(CLOSE, 20)' },
  { label: '量能放大 1.5x', expr: 'VOLUME > MA(VOLUME, 20) * 1.5' },
  { label: '布林上轨突破', expr: 'CLOSE > BOLLUP(CLOSE, 20, 2)' },
  { label: '超卖且站上均线（组合）', expr: '(RSI(14) < 30) && (CLOSE > MA(CLOSE, 20))' },
]

const INTERVAL_OPTIONS = [
  { label: '10 秒', value: 10_000 },
  { label: '30 秒', value: 30_000 },
  { label: '1 分钟', value: 60_000 },
  { label: '5 分钟', value: 300_000 },
]

function requestNotifyPermission() {
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {})
  }
}

function fireBrowserNotification(title: string, body: string) {
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try {
      new Notification(title, { body })
    } catch {
      /* ignore */
    }
  }
}

export function AlertSandboxPanel({ open, onClose, getBars }: Props) {
  const { toast } = useToast()
  const conditions = useAlertSandboxStore((s) => s.conditions)
  const alertLog = useAlertSandboxStore((s) => s.alertLog)
  const addCondition = useAlertSandboxStore((s) => s.addCondition)
  const updateCondition = useAlertSandboxStore((s) => s.updateCondition)
  const removeCondition = useAlertSandboxStore((s) => s.removeCondition)
  const toggleCondition = useAlertSandboxStore((s) => s.toggleCondition)
  const setConditionState = useAlertSandboxStore((s) => s.setConditionState)
  const pushAlert = useAlertSandboxStore((s) => s.pushAlert)
  const clearAlertLog = useAlertSandboxStore((s) => s.clearAlertLog)

  const [intervalMs, setIntervalMs] = useState(30_000)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [expr, setExpr] = useState('')
  const [notify, setNotify] = useState<AlertNotifyMode>('both')
  const [formError, setFormError] = useState<string | null>(null)
  const [snapshots, setSnapshots] = useState<Record<string, ConditionEvalResult>>({})
  const notifAskedRef = useRef(false)

  // 评估全部启用条件并做上升沿检测，命中则写日志 + 通知
  const evalAll = useCallback(() => {
    const bars = getBars()
    if (!bars.length) return
    const st = useAlertSandboxStore.getState()
    const nextSnaps: Record<string, ConditionEvalResult> = {}
    for (const cond of st.conditions) {
      const res = evalCondition(cond, bars)
      nextSnaps[cond.id] = res
      if (!cond.enabled || !res.ok) continue
      const prev = cond.lastState ?? false
      if (!prev && res.state) {
        const lastBar = bars[bars.length - 1]
        pushAlert({
          condId: cond.id,
          condName: cond.name,
          expr: cond.expr,
          time: lastBar.time,
          price: lastBar.close,
          note: `末根估值=${res.value}`,
        })
        toast({
          title: `🔔 条件单命中：${cond.name}`,
          description: `${cond.expr} ｜ ${lastBar.time} 收盘 ${lastBar.close}`,
        })
        if (cond.notify !== 'toast') fireBrowserNotification(`条件单命中：${cond.name}`, `${cond.expr} @ ${lastBar.time} ${lastBar.close}`)
      }
      if (res.state !== prev) setConditionState(cond.id, res.state)
    }
    setSnapshots(nextSnaps)
  }, [getBars, pushAlert, toast, setConditionState])

  // 轮询引擎（沙盒持续评估）
  useEffect(() => {
    if (!open || conditions.length === 0) return
    if (!notifAskedRef.current) {
      notifAskedRef.current = true
      requestNotifyPermission()
    }
    const id = setInterval(evalAll, intervalMs)
    return () => clearInterval(id)
  }, [open, conditions.length, intervalMs, evalAll])

  if (!open) return null

  const startEdit = (cond: AlertCondition) => {
    setEditingId(cond.id)
    setName(cond.name)
    setExpr(cond.expr)
    setNotify(cond.notify)
    setFormError(null)
    setShowForm(true)
  }

  const resetForm = () => {
    setEditingId(null)
    setName('')
    setExpr('')
    setNotify('both')
    setFormError(null)
    setShowForm(false)
  }

  const submitForm = () => {
    if (!name.trim()) return setFormError('请填写条件名称')
    if (!expr.trim()) return setFormError('请填写布尔表达式')
    // 用当前 K 线做一次语法预校验
    const bars = getBars()
    if (bars.length) {
      const probe = evalCondition({ id: 'probe', name, expr: expr.trim(), params: {}, enabled: true, notify, createdAt: 0 }, bars)
      if (!probe.ok) return setFormError(`表达式无效：${probe.error}`)
    }
    const payload = { name: name.trim(), expr: expr.trim(), params: {}, enabled: true, notify }
    if (editingId) updateCondition(editingId, payload)
    else addCondition(payload)
    resetForm()
  }

  return (
    <div className="w-80 shrink-0 h-full border-l border-border/40 bg-background flex flex-col">
      <div className="flex items-center justify-between px-3 h-9 border-b border-border/40 bg-secondary/30 shrink-0">
        <div className="flex items-center gap-1.5 text-xs font-semibold">
          <Bell className="h-3.5 w-3.5 text-primary" />
          条件单沙盒
          <span className="text-[9px] font-normal text-muted-foreground">（模拟推演）</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground" title="关闭">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* 控制条 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/30 text-[10px] shrink-0">
        <span className="text-muted-foreground">轮询</span>
        <select
          value={intervalMs}
          onChange={(e) => setIntervalMs(Number(e.target.value))}
          className="bg-secondary/40 border border-border/40 rounded px-1.5 py-0.5 text-foreground"
        >
          {INTERVAL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Button variant="outline" size="sm" className="h-6 px-2 text-[10px] ml-auto" onClick={evalAll} title="立即评估一次当前 K 线">
          <Play className="h-3 w-3 mr-1" />
          立即评估
        </Button>
        <Button variant="default" size="sm" className="h-6 px-2 text-[10px]" onClick={() => (showForm ? resetForm() : setShowForm(true))}>
          <Plus className="h-3 w-3 mr-1" />
          新建
        </Button>
      </div>

      {/* 新建/编辑表单 */}
      {showForm && (
        <div className="px-3 py-2 border-b border-border/30 bg-secondary/10 space-y-1.5 shrink-0">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="条件名称，如 RSI 超买告警"
            className="w-full bg-background border border-border/40 rounded px-2 py-1 text-[11px]"
          />
          <input
            value={expr}
            onChange={(e) => setExpr(e.target.value)}
            placeholder="布尔表达式，如 RSI(14) > 70"
            className="w-full bg-background border border-border/40 rounded px-2 py-1 text-[11px] font-mono"
          />
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-muted-foreground">通知</span>
            <select
              value={notify}
              onChange={(e) => setNotify(e.target.value as AlertNotifyMode)}
              className="bg-secondary/40 border border-border/40 rounded px-1.5 py-0.5 text-foreground"
            >
              <option value="toast">仅站内</option>
              <option value="push">仅浏览器</option>
              <option value="both">站内 + 浏览器</option>
            </select>
          </div>
          {/* 模板 */}
          <div className="flex flex-wrap gap-1 pt-0.5">
            {TEMPLATES.map((t) => (
              <button
                key={t.label}
                onClick={() => setExpr(t.expr)}
                className="text-[9px] px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20"
                title={t.expr}
              >
                {t.label}
              </button>
            ))}
          </div>
          {formError && <div className="text-[10px] text-red-400 flex items-center gap-1"><AlertCircle className="h-3 w-3" />{formError}</div>}
          <div className="flex gap-2 pt-0.5">
            <Button size="sm" className="h-6 text-[10px]" onClick={submitForm}>
              {editingId ? '保存修改' : '添加条件'}
            </Button>
            <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={resetForm}>
              取消
            </Button>
          </div>
        </div>
      )}

      {/* 条件列表 */}
      <div className="flex-1 overflow-y-auto">
        {conditions.length === 0 && (
          <div className="p-4 text-[10px] text-muted-foreground text-center leading-relaxed">
            暂无监控条件。
            <br />
            点击「新建」并复用指标表达式（支持 &amp;&amp; / || 组合），
            <br />
            后台将持续轮询并在命中时模拟推送通知。
          </div>
        )}
        {conditions.map((cond) => {
          const snap = snapshots[cond.id]
          const state = cond.lastState
          return (
            <div key={cond.id} className="px-3 py-2 border-b border-border/20 text-[11px]">
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => toggleCondition(cond.id)}
                  className="shrink-0"
                  title={cond.enabled ? '点击停用' : '点击启用'}
                >
                  <Power className={`h-3.5 w-3.5 ${cond.enabled ? 'text-emerald-400' : 'text-muted-foreground/50'}`} />
                </button>
                <span className="font-medium truncate flex-1">{cond.name}</span>
                {state === true && <BellRing className="h-3.5 w-3.5 text-amber-400 shrink-0" />}
                <button onClick={() => startEdit(cond)} className="text-muted-foreground hover:text-foreground" title="编辑">
                  <Pencil className="h-3 w-3" />
                </button>
                <button onClick={() => removeCondition(cond.id)} className="text-muted-foreground hover:text-red-400" title="删除">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
              <div className="font-mono text-[9px] text-muted-foreground mt-0.5 truncate">{cond.expr}</div>
              <div className="flex items-center gap-2 mt-0.5 text-[9px]">
                <span className={cond.enabled ? 'text-emerald-400' : 'text-muted-foreground/50'}>
                  {cond.enabled ? '监控中' : '已停用'}
                </span>
                {snap ? (
                  snap.ok ? (
                    <span className={snap.state ? 'text-amber-400' : 'text-sky-400'}>
                      末根估值 {Number(snap.value).toFixed(2)} · {snap.state ? '满足' : '未满足'}
                    </span>
                  ) : (
                    <span className="text-red-400">表达式错误：{snap.error}</span>
                  )
                ) : (
                  <span className="text-muted-foreground/40">未评估</span>
                )}
                {cond.lastTriggeredAt && (
                  <span className="text-muted-foreground/50 ml-auto">
                    {new Date(cond.lastTriggeredAt).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
          )
        })}

        {/* 命中日志 */}
        {alertLog.length > 0 && (
          <div className="border-t border-border/40">
            <div className="flex items-center justify-between px-3 h-7 bg-secondary/30 shrink-0">
              <span className="text-[10px] font-semibold text-muted-foreground">命中日志（alert_logs_sandbox）</span>
              <button onClick={clearAlertLog} className="text-[9px] text-muted-foreground hover:text-red-400">
                清空
              </button>
            </div>
            {alertLog.map((lg) => (
              <div key={lg.id} className="px-3 py-1.5 border-b border-border/10 text-[10px]">
                <div className="flex items-center gap-1.5">
                  <Check className="h-3 w-3 text-amber-400 shrink-0" />
                  <span className="font-medium truncate flex-1">{lg.condName}</span>
                  <span className="text-muted-foreground/50">{new Date(lg.ts).toLocaleTimeString()}</span>
                </div>
                <div className="font-mono text-[9px] text-muted-foreground mt-0.5">
                  {lg.time} 收盘 {lg.price} ｜ {lg.expr}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
