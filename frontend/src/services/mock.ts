// ── 统一的本地数据桩 (Mock Service) ──────────────────────────────
// 集中管理全局零散的 Mock 数据，方便后续根据环境变量统一切换真实 API

// 1. 顶部 Header 跑马灯行情
export const MOCK_HEADER_TICKERS = [
  { symbol: 'BTC/USD', price: 67542.3,  change: 2.14,  dir: 1 },
  { symbol: 'ETH/USD', price: 3452.8,   change: -1.03, dir: -1 },
  { symbol: 'S&P 500', price: 5432.82,  change: 0.89,  dir: 1 },
  { symbol: 'NASDAQ',  price: 17623.45, change: 1.24,  dir: 1 },
  { symbol: 'VIX',     price: 14.25,    change: -8.32, dir: -1 },
  { symbol: 'DXY',     price: 104.32,   change: 0.12,  dir: 1 },
]

// 2. 自选股 Watchlist 默认列表
export const MOCK_WATCHLIST = [
  { symbol: 'BTC/USD', price: 67542.3,  change: 2.14,  vol: '32.4B', sparkDir: [1,1,-1,1,1,1,-1,1] },
  { symbol: 'ETH/USD', price: 3452.8,   change: -1.03, vol: '14.2B', sparkDir: [1,-1,-1,1,-1,-1,1,-1] },
  { symbol: '00700.HK',price: 372.8,    change: 0.54,  vol: '2.1B',  sparkDir: [1,1,1,-1,1,-1,1,1] },
  { symbol: 'SOL/USD', price: 175.42,   change: 3.28,  vol: '4.8B',  sparkDir: [1,1,1,1,-1,1,1,1] },
  { symbol: 'SPY',     price: 543.12,   change: 0.89,  vol: '28.7B', sparkDir: [1,-1,1,1,1,-1,1,1] },
]

// 3. 选股器 (Screener) 默认结果
export const MOCK_SCREENER_RESULTS = [
  { rank: 1,  symbol: '00700.HK', name: '腾讯控股',   sector: '科技', mktcap: '3.21T', price: 372.8,  chg: 0.54,  rsi: 28.5, inflow: '+12.3M', chg30: '+18.5%', score: 94 },
  { rank: 2,  symbol: '09988.HK', name: '阿里巴巴-W', sector: '科技', mktcap: '1.87T', price: 85.5,   chg: -0.58, rsi: 32.1, inflow: '+8.7M',  chg30: '+15.2%', score: 89 },
  { rank: 3,  symbol: '01810.HK', name: '小米集团-W', sector: '科技', mktcap: '0.45T', price: 18.9,   chg: 1.23,  rsi: 25.3, inflow: '+5.2M',  chg30: '+22.1%', score: 87 },
  { rank: 4,  symbol: '06618.HK', name: '京东物流',   sector: '物流', mktcap: '0.12T', price: 14.5,   chg: 0.35,  rsi: 19.8, inflow: '+3.1M',  chg30: '+9.5%',  score: 81 },
  { rank: 5,  symbol: 'NVDA',     name: 'NVIDIA',     sector: '半导体','mktcap': '2.9T', price: 1189.2, chg: 2.18,  rsi: 41.2, inflow: '+45.2M', chg30: '+28.4%', score: 92 },
  { rank: 6,  symbol: 'TSMC',     name: '台积电',     sector: '半导体','mktcap': '0.9T', price: 174.5,  chg: -0.42, rsi: 36.8, inflow: '+11.3M', chg30: '+12.8%', score: 85 },
]

// 4. Quotes DOM 十档盘口数据生成器
export function generateMockOrders(isBid: boolean) {
  const base = 67542
  return Array.from({ length: 10 }, (_, i) => {
    const offset = (i + 1) * (isBid ? -15 : 15)
    const pseudoRand = ((i * 13) % 10) / 10
    const size = pseudoRand * 3 + 0.1
    const total = base * size
    return { price: base + offset, size: size.toFixed(3), total: (total / 1000).toFixed(1) + 'K', depth: pseudoRand }
  })
}

// 5. Quotes 近期成交流水
export const MOCK_RECENT_TRADES = Array.from({ length: 16 }, (_, i) => {
  const pseudoRand = ((i * 17) % 10) / 10
  return {
    price: 67542 + pseudoRand * 200 - 100,
    size: (pseudoRand * 2 + 0.01).toFixed(3),
    side: pseudoRand > 0.5 ? 'buy' : 'sell',
    time: new Date(1717200000000 - i * 8000).toISOString().substring(11, 19),
  }
})

// 6. Quotes 宏观日历事件点阵
export const MOCK_PRICE_EVENTS = [
  { date: '06-15', label: 'Q2 财报', impact: 'high' as const },
  { date: '06-20', label: '美国非农', impact: 'high' as const },
  { date: '06-25', label: 'FOMC', impact: 'high' as const },
]

// 7. 跨市场资金流向
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

export const MOCK_CAPITAL_FLOWS: CapitalFlowItem[] = [
  {
    market: 'HK',
    label: '港股南向',
    amount: 12.8,
    unit: '亿港元',
    dir: 1,
    desc: '沪深港通净买入港股',
    sparkDirs: [1, 1, -1, 1, 1, 1, -1, 1],
  },
  {
    market: 'CN',
    label: 'A股北向',
    amount: -5.3,
    unit: '亿人民币',
    dir: -1,
    desc: '外资沪深股通净卖出A股',
    sparkDirs: [-1, -1, 1, -1, -1, 1, -1, -1],
  },
  {
    market: 'US',
    label: '美股机构',
    amount: 2.1,
    unit: '十亿美元',
    dir: 1,
    desc: 'SPY/QQQ 大单净流入',
    sparkDirs: [1, 1, 1, -1, 1, 1, 1, 1],
  },
  {
    market: 'HK',
    label: '港股外资',
    amount: -3.2,
    unit: '亿港元',
    dir: -1,
    desc: '外资主买/主卖净差',
    sparkDirs: [-1, 1, -1, -1, -1, 1, -1, -1],
  },
  {
    market: 'CN',
    label: 'A股主力',
    amount: 8.7,
    unit: '亿人民币',
    dir: 1,
    desc: '超大单净流入',
    sparkDirs: [1, 1, 1, 1, -1, 1, 1, 1],
  },
  {
    market: 'US',
    label: '美债资金',
    amount: -1.8,
    unit: '十亿美元',
    dir: -1,
    desc: 'TLT/HYG 资金流出',
    sparkDirs: [-1, -1, -1, 1, -1, -1, -1, -1],
  },
]

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