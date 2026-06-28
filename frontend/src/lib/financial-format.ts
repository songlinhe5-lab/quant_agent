/**
 * 金融数据格式化工具
 * FE-09: 涨跌颜色动态切换（中国市场红涨绿跌 / 欧美市场绿涨红跌）
 * FE-10: 等宽字体 tabular-nums
 */

import { cn } from '@/lib/utils'

// ─── 市场区域配置 ──────────────────────────────────────────────────
export type MarketRegion = 'CN' | 'HK' | 'US' | 'EU'

// 涨跌颜色方案
interface ColorScheme {
  up: string      // 上涨颜色
  down: string    // 下跌颜色
  flat: string    // 平盘颜色
}

// 中国市场：红涨绿跌
const CN_COLOR_SCHEME: ColorScheme = {
  up: 'text-red-500',
  down: 'text-emerald-500',
  flat: 'text-muted-foreground',
}

// 欧美市场：绿涨红跌
const US_COLOR_SCHEME: ColorScheme = {
  up: 'text-emerald-500',
  down: 'text-red-500',
  flat: 'text-muted-foreground',
}

// 颜色方案映射
const COLOR_SCHEMES: Record<MarketRegion, ColorScheme> = {
  CN: CN_COLOR_SCHEME,
  HK: CN_COLOR_SCHEME,  // 港股跟随 A 股习惯
  US: US_COLOR_SCHEME,
  EU: US_COLOR_SCHEME,
}

// ─── 全局配置 ──────────────────────────────────────────────────────
let currentRegion: MarketRegion = 'CN'

/**
 * 设置当前市场区域
 */
export function setMarketRegion(region: MarketRegion): void {
  currentRegion = region
  // 同步到 DOM，供 CSS 使用
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.marketRegion = region
  }
}

/**
 * 获取当前市场区域
 */
export function getMarketRegion(): MarketRegion {
  return currentRegion
}

/**
 * 获取当前颜色方案
 */
export function getColorScheme(): ColorScheme {
  return COLOR_SCHEMES[currentRegion]
}

// ─── 涨跌颜色 Hook ────────────────────────────────────────────────
/**
 * 获取涨跌对应的颜色类名
 * @param value 变化值（正数=上涨，负数=下跌，0=平盘）
 * @param region 可选，指定市场区域
 */
export function getChangeColor(value: number, region?: MarketRegion): string {
  const scheme = region ? COLOR_SCHEMES[region] : getColorScheme()
  if (value > 0) return scheme.up
  if (value < 0) return scheme.down
  return scheme.flat
}

/**
 * 获取涨跌对应的背景色类名
 */
export function getChangeBgColor(value: number, region?: MarketRegion): string {
  if (region === 'CN' || (!region && currentRegion === 'CN' || currentRegion === 'HK')) {
    // 中国市场
    if (value > 0) return 'bg-red-500/10'
    if (value < 0) return 'bg-emerald-500/10'
    return 'bg-muted/50'
  } else {
    // 欧美市场
    if (value > 0) return 'bg-emerald-500/10'
    if (value < 0) return 'bg-red-500/10'
    return 'bg-muted/50'
  }
}

// ─── 金融数字格式化 ────────────────────────────────────────────────
/**
 * 格式化价格
 */
export function formatPrice(price: number, decimals: number = 2): string {
  return price.toFixed(decimals)
}

/**
 * 格式化涨跌幅
 */
export function formatChange(change: number, withSign: boolean = true): string {
  const sign = withSign && change > 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}%`
}

/**
 * 格式化大数字（成交量、市值等）
 */
export function formatLargeNumber(num: number): string {
  if (num >= 1e12) return `${(num / 1e12).toFixed(2)}T`
  if (num >= 1e9) return `${(num / 1e9).toFixed(2)}B`
  if (num >= 1e6) return `${(num / 1e6).toFixed(2)}M`
  if (num >= 1e3) return `${(num / 1e3).toFixed(2)}K`
  return num.toFixed(2)
}

/**
 * 格式化货币
 */
export function formatCurrency(amount: number, currency: 'USD' | 'HKD' | 'CNY' = 'USD'): string {
  const symbols = { USD: '$', HKD: 'HK$', CNY: '¥' }
  return `${symbols[currency]}${Math.abs(amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// ─── React 组件辅助 ────────────────────────────────────────────────
/**
 * 涨跌数字组件类名生成器
 * 自动应用 tabular-nums + 涨跌颜色
 */
export function getFinancialNumberClasses(
  value: number,
  options: {
    region?: MarketRegion
    size?: 'sm' | 'md' | 'lg'
    bold?: boolean
  } = {}
): string {
  const { region, size = 'md', bold = true } = options
  
  const sizeClasses = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-base',
  }

  return cn(
    'tabular-nums font-mono',  // FE-10: 等宽字体
    sizeClasses[size],
    bold && 'font-semibold',
    getChangeColor(value, region)
  )
}

// ─── CSS 变量（供 Tailwind 使用）──────────────────────────────────
/**
 * 生成 CSS 变量字符串
 * 可在组件 style 属性中使用
 */
export function getMarketCSSVariables(region: MarketRegion): string {
  const scheme = COLOR_SCHEMES[region]
  const colors = {
    CN: { up: '#ef4444', down: '#10b981' },  // 红涨绿跌
    HK: { up: '#ef4444', down: '#10b981' },
    US: { up: '#10b981', down: '#ef4444' },  // 绿涨红跌
    EU: { up: '#10b981', down: '#ef4444' },
  }
  
  const c = colors[region]
  return `--color-up: ${c.up}; --color-down: ${c.down};`
}
