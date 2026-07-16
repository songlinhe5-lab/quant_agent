/**
 * Calendars 模块纯函数工具（FE-PROD-05）
 * 抽离便于 Vitest 单测，避免依赖 React / 网络。
 */

export interface CalendarTile {
  symbol: string
  display_name: string
  yf_ticker: string
  price: number
  change_abs: number
  change_pct: number
  sparkline: number[]
  updated_at: string | null
  is_stale: boolean
  source: string
  category: string
}

export interface CalendarCategoryView {
  category: string
  display_name: string
  is_market_open: boolean
  next_session_change: string | null
  tiles: CalendarTile[]
}

/**
 * 按用户隐藏清单过滤类目（自定义类目可见性，FE-PROD-05f）。
 */
export function filterVisibleCategories(
  categories: CalendarCategoryView[],
  hidden: string[],
): CalendarCategoryView[] {
  if (!hidden || hidden.length === 0) return categories
  return categories.filter((c) => !hidden.includes(c.category))
}

/**
 * 将 ISO 时间字符串按目标时区格式化（默认 zh-CN 月/日 时:分）。
 */
export function formatTimeInZone(iso: string | null, tz: string): string {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '--'
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: tz,
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(d)
  } catch {
    return '--'
  }
}

/**
 * 类目 → 锚点 id（用于侧栏点击平滑滚动）。
 */
export function categoryAnchorId(category: string): string {
  return `cal-cat-${category}`
}
