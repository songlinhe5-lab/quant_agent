/**
 * 告警中心类型定义 (ALERT-04)
 * 对齐后端 backend/routers/alert.py 的 Schema
 */

// ─── 枚举 ──────────────────────────────────────────────────────────

export type AlertRuleType = 'price_cross' | 'price_above' | 'price_below' | 'indicator' | 'strategy_signal' | 'macro_event' | 'rsi_threshold' | 'macd_cross' | 'ma_cross'

export type AlertSeverity = 'info' | 'warning' | 'critical'

export type AlertChannel = 'in_app' | 'feishu' | 'telegram'

export type NotificationPriority = 'p0' | 'p1' | 'p2' | 'p3'

// ─── 规则 ──────────────────────────────────────────────────────────

export interface AlertRule {
  rule_id: string
  name: string
  ticker: string
  rule_type: AlertRuleType
  threshold: number
  severity: AlertSeverity
  channels: AlertChannel[]
  cooldown_seconds: number
  enabled: boolean
  trigger_count: number
  last_triggered_at: number | null
  created_at: number
  updated_at: number
}

// ─── 事件 ──────────────────────────────────────────────────────────

export interface AlertEvent {
  event_id: string
  rule_id: string
  ticker: string
  rule_type: AlertRuleType | null
  severity: AlertSeverity
  message: string
  trigger_value: number | null
  threshold: number | null
  triggered_at: number
  acknowledged: boolean
  source: string
  priority: NotificationPriority | null
  /** 前端行为提示：route/symbol 跳转、mode/flash 等 */
  ui_hint?: AlertUiHint
}

/** docs/01 §10.5 · InAppAdapter 推送体 */
export interface AlertUiHint {
  mode?: 'fullscreen' | 'toast' | 'statusbar' | 'badge' | string
  flash?: boolean
  sound?: boolean
  duration?: number
  route?: string
  symbol?: string
  [key: string]: unknown
}

export interface AlertPushPayload {
  type: 'alert'
  event_id: string
  priority: NotificationPriority
  severity: AlertSeverity
  message: string
  ticker: string
  triggered_at: number
  ui_hint: AlertUiHint
  rule_id: string
  source: string
  ack_required: boolean
}

// ─── 引擎状态 ──────────────────────────────────────────────────────

export interface AlertEngineStatus {
  running: boolean
  active_rules: number
  eval_count: number
  trigger_count: number
  tracked_tickers: number
  dispatcher: Record<string, unknown> | null
}

// ─── 投递记录 ──────────────────────────────────────────────────────

export interface DeliveryRecord {
  delivery_id: string
  event_id: string
  channel: string
  priority: string
  status: string
  attempt: number
  latency_ms: number | null
  error: string | null
  created_at: number
}

// ─── 创建规则请求 ──────────────────────────────────────────────────

export interface CreateRulePayload {
  name: string
  ticker: string
  rule_type: AlertRuleType
  threshold: number
  severity?: AlertSeverity
  channels?: AlertChannel[]
  cooldown_seconds?: number
  metadata?: Record<string, unknown>
}

// ─── 更新规则请求 ──────────────────────────────────────────────────

export interface UpdateRulePayload {
  name?: string
  threshold?: number
  severity?: AlertSeverity
  channels?: AlertChannel[]
  cooldown_seconds?: number
  metadata?: Record<string, unknown>
}

// ─── 常量 ──────────────────────────────────────────────────────────

export const RULE_TYPE_LABELS: Record<AlertRuleType, string> = {
  price_cross: '价格穿越',
  price_above: '价格突破',
  price_below: '价格跌破',
  indicator: '技术指标',
  strategy_signal: '策略信号',
  macro_event: '宏观事件',
  // ALERT-05: 技术指标告警
  rsi_threshold: 'RSI 超买超卖',
  macd_cross: 'MACD 金叉死叉',
  ma_cross: '均线穿越',
}

export const SEVERITY_LABELS: Record<AlertSeverity, string> = {
  info: '信息',
  warning: '警告',
  critical: '严重',
}

export const SEVERITY_COLORS: Record<AlertSeverity, string> = {
  info: 'text-blue-500',
  warning: 'text-amber-500',
  critical: 'text-red-500',
}

export const PRIORITY_COLORS: Record<NotificationPriority, string> = {
  p0: 'bg-red-500',
  p1: 'bg-amber-500',
  p2: 'text-blue-500',
  p3: 'text-slate-500',
}
