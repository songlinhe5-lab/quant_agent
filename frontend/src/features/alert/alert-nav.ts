import type { AlertPushPayload, AlertUiHint, NotificationPriority, AlertSeverity } from '@/types/alert'

const PRIORITIES = new Set(['p0', 'p1', 'p2', 'p3'])

/** 解析 InApp WS / 兼容残缺字段 */
export function parseAlertPush(raw: unknown): AlertPushPayload | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (o.type !== 'alert' && !o.event_id) return null
  const eventId = String(o.event_id || '')
  if (!eventId) return null

  const priority = (PRIORITIES.has(String(o.priority)) ? String(o.priority) : 'p1') as NotificationPriority
  const severity = (['info', 'warning', 'critical'].includes(String(o.severity))
    ? String(o.severity)
    : 'warning') as AlertSeverity

  const uiHint = (typeof o.ui_hint === 'object' && o.ui_hint !== null
    ? (o.ui_hint as AlertUiHint)
    : {}) as AlertUiHint

  return {
    type: 'alert',
    event_id: eventId,
    priority,
    severity,
    message: String(o.message || '告警触发'),
    ticker: String(o.ticker || ''),
    triggered_at: typeof o.triggered_at === 'number' ? o.triggered_at : Date.now() / 1000,
    ui_hint: uiHint,
    rule_id: String(o.rule_id || ''),
    source: String(o.source || 'user_rule'),
    ack_required: Boolean(o.ack_required) || priority === 'p0',
  }
}

/**
 * 将 ui_hint 解析为站内路径。
 * 约定：`/market` + symbol → `/quotes`（写入 sessionStorage）；其它 route 原样。
 */
export function resolveAlertNavigation(hint: AlertUiHint | undefined, ticker?: string): {
  path: string
  symbol?: string
} {
  const symbol = (hint?.symbol as string | undefined) || ticker || undefined
  const route = (hint?.route as string | undefined) || (symbol ? '/market' : '/alerts')

  if (route === '/market' || route.startsWith('/market/')) {
    return { path: '/quotes', symbol }
  }
  if (route === '/quotes' && symbol) {
    return { path: '/quotes', symbol }
  }
  return { path: route.startsWith('/') ? route : `/${route}`, symbol }
}

export function applyAlertNavigation(
  navigate: (to: string) => void,
  hint: AlertUiHint | undefined,
  ticker?: string,
) {
  const { path, symbol } = resolveAlertNavigation(hint, ticker)
  if (symbol && path === '/quotes') {
    sessionStorage.setItem('quant_target_symbol', symbol)
  }
  navigate(path)
}
