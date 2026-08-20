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
  { name: 'Beta', desc: '市场敏感度 (OLS vs 基准)。>1 波动大于大盘，<1 相对稳健' },
  { name: 'Vol', desc: '年化波动率。60 日日收益率标准差，越高越不稳定' },
  { name: 'Liq', desc: '流动性评分(简化代理)。基于持仓收益率波动的倒数估算，波动越低流动性越好' },
  { name: 'Corr', desc: '持仓相关性。取 60 日相关矩阵非对角均值，越低分散化越好' },
  { name: 'Mom', desc: '动量因子。50 + 20 日对数动量均值 × 200，极端值暗示反转风险' },
  { name: 'DD', desc: '最大回撤。NAV 快照序列计算的净值峰值跌幅' },
]

export const FACTOR_HELP = [
  { name: 'Market Beta', desc: '组合相对大盘敏感度。=1 同步，>1 波动更大，<1 更防御' },
  { name: 'VaR (95%)', desc: '95% 置信下单日最大预期亏损。60 日历史模拟法。金额 = |日收益5分位| × 当前净值' },
  { name: 'Sharpe', desc: '(年化收益 - 无风险利率) / 波动率。>1.5 优秀，<1.0 补偿不足' },
  { name: 'Max DD', desc: '净值峰值到最低点的最大跌幅。极端行情账面亏损幅度' },
]

// ── 风险分级单一 SSOT (诊断 7: 消除与 lib/constants.ts 的语义冲突) ──────────
export const RISK_LEVEL_META: Array<{
  min: number
  label: string
  color: string
}> = [
  { min: 70, label: '高风险', color: '#ef4444' },
  { min: 50, label: '中高风险', color: '#f59e0b' },
  { min: 30, label: '中等风险', color: '#3b82f6' },
  { min: 0, label: '低风险', color: '#10b981' },
]

export function riskLevelOf(score: number) {
  return RISK_LEVEL_META.find(l => score >= l.min) || RISK_LEVEL_META[RISK_LEVEL_META.length - 1]
}
