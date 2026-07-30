// ── 统一的本地数据桩 (Mock Service) ──────────────────────────────
// 集中管理全局零散的 Mock 数据，方便后续根据环境变量统一切换真实 API

// §14.1 生产环境零 Mock 数据：mock 仅限 DEV + 显式开关 VITE_ENABLE_MOCK，
// PROD 构建下 import.meta.env.DEV 为 false，MOCK_ENABLED 恒为 false。
// 所有 MOCK_* 值的使用方都必须用此开关门控（CI 会扫描未门控的引用）。
export const MOCK_ENABLED =
  import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCK === 'true'

// 自选股 Watchlist 默认列表（§14.1：仅 DEV + VITE_ENABLE_MOCK 下由 use-watchlist 使用）
export const MOCK_WATCHLIST = [
  { symbol: 'BTC/USD', price: 67542.3,  change: 2.14,  vol: '32.4B', sparkDir: [1,1,-1,1,1,1,-1,1] },
  { symbol: 'ETH/USD', price: 3452.8,   change: -1.03, vol: '14.2B', sparkDir: [1,-1,-1,1,-1,-1,1,-1] },
  { symbol: '00700.HK',price: 372.8,    change: 0.54,  vol: '2.1B',  sparkDir: [1,1,1,-1,1,-1,1,1] },
  { symbol: 'SOL/USD', price: 175.42,   change: 3.28,  vol: '4.8B',  sparkDir: [1,1,1,1,-1,1,1,1] },
  { symbol: 'SPY',     price: 543.12,   change: 0.89,  vol: '28.7B', sparkDir: [1,-1,1,1,1,-1,1,1] },
]

// 跨市场资金流向
export interface CapitalFlowItem {
  market: string
  label: string
  amount: number
  unit: string
  dir: number // 1 = 净流入, -1 = 净流出
  desc: string
  sparkDirs: number[]
  data_source?: string  // 💡 数据来源
  updated_at?: string   // 💡 更新时间
}

// 8. 大类资产走势
export interface AssetTrendItem {
  symbol: string
  name: string
  category: string
  price: number
  basePrice: number
  changePct: number
  unit?: string
  volatility?: number
  sparkDirs: number[]
  subtitle?: {
    label: string
    value: string
    dir: number
  }
  desc30d?: string
  data_source?: string  // 💡 数据来源
  updated_at?: string   // 💡 更新时间
}

export const MOCK_ASSET_TRENDS: AssetTrendItem[] = [
  {
    symbol: 'SPX',
    name: '标普 500',
    category: '美股',
    price: 5234.18,
    basePrice: 5200,
    changePct: 0.65,
    sparkDirs: [1, -1, 1, 1, -1, 1, 1, -1, 1, 1],
    subtitle: { label: 'VIX', value: '14.2', dir: -1 },
    desc30d: '过去30天受AI企业财报提振，整体维持高位震荡，注意短期回调风险。'
  },
  {
    symbol: 'HSI',
    name: '恒生指数',
    category: '港股',
    price: 18456.2,
    basePrice: 18500,
    changePct: -0.24,
    sparkDirs: [-1, -1, 1, -1, -1, 1, -1, -1, 1, -1],
    subtitle: { label: '南向资金', value: '34.2亿', dir: 1 },
    desc30d: '南向资金持续抄底，但受外围宏观压制，在18000点附近反复筑底。'
  },
  {
    symbol: 'US10Y',
    name: '美债 10年期',
    category: '债券',
    price: 4.25,
    basePrice: 4.2,
    changePct: 1.19,
    unit: '%',
    volatility: 0.01,
    sparkDirs: [1, 1, 1, -1, 1, 1, -1, 1, 1, 1],
    subtitle: { label: '加息预期', value: '5.25%', dir: 0 },
    desc30d: '通胀数据超预期，降息预期延后，长债收益率持续在高位盘整。'
  },
  {
    symbol: 'XAUUSD',
    name: '黄金',
    category: '大宗',
    price: 2345.6,
    basePrice: 2320,
    changePct: 1.10,
    unit: '盎司',
    volatility: 0.005,
    sparkDirs: [-1, 1, 1, 1, -1, 1, 1, 1, 1, 1],
    subtitle: { label: '实物需求', value: '强劲', dir: 1 },
    desc30d: '避险情绪与央行购金双重驱动，连续突破历史新高，多头趋势强劲。'
  },
  {
    symbol: 'BTCUSD',
    name: '比特币',
    category: '加密',
    price: 67890.0,
    basePrice: 65000,
    changePct: 4.44,
    volatility: 0.015,
    sparkDirs: [1, -1, 1, 1, 1, -1, 1, 1, 1, 1],
    subtitle: { label: 'ETF净流入', value: '2.1亿', dir: 1 },
    desc30d: 'ETF净流入放缓，现货抛压增加，高位箱体震荡，支撑位65000。'
  }
]