/**
 * 风控模块类型定义 & 常量
 */

// ── Types ───────────────────────────────────────────────────────────────

export interface KpiData {
  nav: number
  nav_fmt: string
  today_pl: number
  today_pl_fmt: string
  today_pl_pct: number
  cash: number
  cash_fmt: string
  leverage: number
  leverage_fmt: string
  currency: string
}

export interface ExposureData { name: string; value: number; pct: number; color: string; lightColor: string }
export interface RiskRadarData { axis: string; current: number; limit: number }
export interface RiskFactorData { label: string; value: number; threshold: number; unit: string; status: 'safe' | 'warn' | 'good' | 'crit' }
export interface NavSnapshot { ts: number; nav: number }
export interface PositionData { code: string; stock_name?: string; position_side?: string; qty?: number; market_val?: number; pl_val?: number; pl_ratio?: number; market?: string }

export interface CorrelationData { labels: string[]; matrix: number[][]; warnings: { a: string; b: string; val: number }[] }
export interface SectorData { sector: string; pct: number; market_val: number; symbols: string[] }
export interface CVarData { symbol: string; cvar_contrib: number; weight: number; marginal_var: number }

export interface AccountDetail {
  kpi: KpiData
  exposure: ExposureData[]
  risk_radar: RiskRadarData[]
  risk_factors: RiskFactorData[]
  nav_snapshots: NavSnapshot[]
  correlation?: CorrelationData
  positions: PositionData[]
  currency: string
  position_count: number
}

export type AccountsMap = Record<string, AccountDetail>

// ── Constants ───────────────────────────────────────────────────────────────

export const MARKET_LABELS: Record<string, { name: string; flag: string; currency: string }> = {
  HK: { name: '港股模拟账户', flag: '🇭🇰', currency: 'HKD' },
  US: { name: '美股模拟账户', flag: '🇺🇸', currency: 'USD' },
}

export const statusMeta = {
  safe: { label: '安全', cls: 'text-emerald-500', bg: 'bg-emerald-500/10 border-emerald-500/20', dot: 'bg-emerald-500' },
  warn: { label: '预警', cls: 'text-amber-500', bg: 'bg-amber-500/10 border-amber-500/20', dot: 'bg-amber-500' },
  good: { label: '优秀', cls: 'text-sky-500', bg: 'bg-sky-500/10 border-sky-500/20', dot: 'bg-sky-500' },
  crit: { label: '超限', cls: 'text-red-500', bg: 'bg-red-500/10 border-red-500/20', dot: 'bg-red-500' },
}

export const RADAR_HELP = [
  { name: 'Beta', desc: '市场敏感度。>1 波动大于大盘，<1 相对稳健' },
  { name: 'Vol', desc: '年化波动率。60 日日收益率标准差，越高越不稳定' },
  { name: 'Liq', desc: '流动性评分。基于持仓市值与成交量估算变现难度' },
  { name: 'Corr', desc: '持仓相关性。越低分散化越好，过高则风险集中' },
  { name: 'Mom', desc: '动量因子。近期趋势强度，极端值暗示反转风险' },
  { name: 'DD', desc: '最大回撤。NAV 快照序列计算的净值峰值跌幅' },
]

export const FACTOR_HELP = [
  { name: 'Market Beta', desc: '组合相对大盘敏感度。=1 同步，>1 波动更大，<1 更防御' },
  { name: 'VaR (95%)', desc: '95% 置信下单日最大预期亏损。60 日历史模拟法' },
  { name: 'Sharpe', desc: '(年化收益 - 无风险利率) / 波动率。>1.5 优秀，<1.0 补偿不足' },
  { name: 'Max DD', desc: '净值峰值到最低点的最大跌幅。极端行情账面亏损幅度' },
]
