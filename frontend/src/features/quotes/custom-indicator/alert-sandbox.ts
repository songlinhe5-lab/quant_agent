// ALERT-COND-01: 条件单沙盒（Conditional Order Sandbox）
// 复用自定义指标的布尔表达式引擎，将「指标 + 运算符 + 阈值」的组合封装为可持久化、
// 可后台轮询评估的告警条件。当前 OMS 未实装，仅做模拟命中通知（Toast / 浏览器 Push），
// 命中记录写入本地 alert_logs（等价后端 alert_logs_sandbox 表），待实盘切换后可直接复用为真条件单。

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { evaluate, type CIBar } from './engine'

export type AlertNotifyMode = 'toast' | 'push' | 'both'

export interface AlertCondition {
  id: string
  name: string
  /** 布尔表达式，如 RSI(14) > 70 或 (RSI(14) < 30) && (CLOSE > MA(CLOSE, 20)) */
  expr: string
  /** @参数 代入表（可选） */
  params?: Record<string, number>
  /** 是否启用后台轮询监控 */
  enabled: boolean
  /** 命中通知方式 */
  notify: AlertNotifyMode
  createdAt: number
  /** 上次评估命中状态（用于上升沿边沿检测） */
  lastState?: boolean
  /** 上次命中时间（ms） */
  lastTriggeredAt?: number
}

export interface AlertLogEntry {
  id: string
  condId: string
  condName: string
  expr: string
  /** 命中 K 线日期 */
  time: string
  /** 命中时间戳 */
  ts: number
  /** 命中时收盘价 */
  price?: number
  /** 命中时表达式末根数值（估值快照） */
  note?: string
}

export interface ConditionEvalResult {
  ok: boolean
  state: boolean
  error?: string
  value?: number
}

/** 评估单条条件对末根 K 线的满足情况 */
export function evalCondition(cond: AlertCondition, bars: CIBar[]): ConditionEvalResult {
  if (!bars || bars.length === 0) return { ok: false, state: false, error: '无 K 线数据' }
  try {
    const v = evaluate(cond.expr, bars, cond.params)
    if (!v.ok) return { ok: false, state: false, error: '表达式无效' }
    const last = [...v.values].reverse().find((x) => x != null)
    if (last == null) return { ok: false, state: false, error: '末根无有效值' }
    return { ok: true, state: last === 1, value: last }
  } catch (e) {
    return { ok: false, state: false, error: e instanceof Error ? e.message : String(e) }
  }
}

interface AlertSandboxState {
  conditions: AlertCondition[]
  alertLog: AlertLogEntry[]
  addCondition: (c: Omit<AlertCondition, 'id' | 'createdAt'>) => string
  updateCondition: (id: string, patch: Partial<AlertCondition>) => void
  removeCondition: (id: string) => void
  toggleCondition: (id: string) => void
  /** 更新条件的评估状态（边沿检测用），命中时顺带写入 lastTriggeredAt */
  setConditionState: (id: string, state: boolean) => void
  pushAlert: (entry: Omit<AlertLogEntry, 'id' | 'ts'>) => void
  clearAlertLog: () => void
}

function genId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export const useAlertSandboxStore = create<AlertSandboxState>()(
  persist(
    (set) => ({
      conditions: [],
      alertLog: [],
      addCondition: (c) => {
        const id = genId('al')
        set((s) => ({ conditions: [...s.conditions, { ...c, id, createdAt: Date.now() }] }))
        return id
      },
      updateCondition: (id, patch) =>
        set((s) => ({ conditions: s.conditions.map((c) => (c.id === id ? { ...c, ...patch } : c)) })),
      removeCondition: (id) => set((s) => ({ conditions: s.conditions.filter((c) => c.id !== id) })),
      toggleCondition: (id) =>
        set((s) => ({ conditions: s.conditions.map((c) => (c.id === id ? { ...c, enabled: !c.enabled } : c)) })),
      setConditionState: (id, state) =>
        set((s) => ({
          conditions: s.conditions.map((c) =>
            c.id === id ? { ...c, lastState: state, lastTriggeredAt: state ? Date.now() : c.lastTriggeredAt } : c,
          ),
        })),
      pushAlert: (entry) =>
        set((s) => ({
          alertLog: [{ ...entry, id: genId('lg'), ts: Date.now() }, ...s.alertLog].slice(0, 200),
        })),
      clearAlertLog: () => set({ alertLog: [] }),
    }),
    {
      name: 'quant-alert-sandbox',
      version: 1,
      partialize: (s) => ({ conditions: s.conditions.map(({ lastState: _ls, lastTriggeredAt: _lt, ...rest }) => rest), alertLog: s.alertLog }),
    },
  ),
)
