import React from 'react'
import { TrendingUp, TrendingDown, Clock, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface MarginMarketData {
  market: string
  market_name: string
  financing_balance: number
  securities_balance: number
  financing_change: number
  securities_change: number
  unit: string
  updated_at: string
  source: string
  note?: string
  // 港股/美股卖空指标口径（监管底层，与 A 股两融余额概念不同）
  short_sale_volume?: number | null
  total_volume?: number | null
  short_volume_ratio?: number | null
  short_interest_shares?: number | null
  short_interest_ratio?: number | null
  as_of?: string
  sources?: string[]
}

interface MarginTradingPanelProps {
  data: MarginMarketData[]
  status?: string
  lastUpdated?: string
}

// 安全格式化更新时间：lastUpdated 可能已是格式化好的时间字符串（如 "15:20:33"），
// 若再次 new Date() 解析会失败得到 Invalid Date。因此先尝试解析，失败时原样返回字符串。
function formatUpdatedAt(v: string | undefined): string {
  if (!v) return ''
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleTimeString('zh-CN', { hour12: false })
}

function MarketMarginCard({ data }: { data: MarginMarketData }) {
  const financingUp = (data.financing_change ?? 0) >= 0
  const securitiesUp = (data.securities_change ?? 0) >= 0

  // A 股使用两融余额口径；港股/美股使用监管卖空指标口径（概念不同，不强行对齐）
  const isMarginBalanceMarket = data.market === 'A_SHARE'
  const hasShortMetrics =
    data.short_sale_volume != null ||
    data.short_volume_ratio != null ||
    data.short_interest_shares != null ||
    data.short_interest_ratio != null

  // 卖空数据源标签：优先取后端返回的 sources 真实源，否则按市场回退（零幻觉红线：标注必须与数据实际来源一致）
  // - 美股：卖空余额/回补天数来自 CBOE（公开做空持仓），做空成交占比来自 FINRA
  // - 港股：卖空余额来自 SFC（淡仓申报），做空成交占比来自 HKEX
  const src = (data.sources || []).join(' ').toLowerCase()
  const srcLabel = (field: 'ratio' | 'interest') => {
    if (src.includes('cboe')) return 'CBOE'
    if (src.includes('finra')) return 'FINRA'
    if (src.includes('sfc')) return 'SFC'
    if (src.includes('hkex')) return 'HKEX'
    if (data.market === 'US_SHARE') return field === 'ratio' ? 'FINRA' : 'CBOE'
    return field === 'ratio' ? 'HKEX' : 'SFC'
  }

  // 格式化数字显示（DIST-SEC-01 配套：字段缺失时兜底为 '--'）
  const formatNumber = (num: number | null | undefined) => {
    if (num == null || Number.isNaN(num)) return '--'
    return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  // 格式化变化量（DIST-SEC-01 配套：字段缺失时兜底为 '--'）
  const formatChange = (num: number | null | undefined) => {
    if (num == null || Number.isNaN(num)) return '--'
    const sign = num >= 0 ? '+' : ''
    return `${sign}${num.toFixed(2)}`
  }

  // 大数字（股数）紧凑显示：亿/万
  const formatShares = (n: number | null | undefined) => {
    if (n == null || Number.isNaN(n)) return '--'
    if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿股`
    if (n >= 1e4) return `${(n / 1e4).toFixed(2)} 万股`
    return `${n.toLocaleString('zh-CN')} 股`
  }
  const formatRatio = (n: number | null | undefined) => {
    if (n == null || Number.isNaN(n)) return '--'
    return `${n.toFixed(2)}%`
  }

  return (
    <div className="glass-panel p-3 rounded-xl border border-border/20 hover:border-primary/30 transition-all duration-300">
      {/* 市场标题 */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-sm">
            {data.market === 'A_SHARE' ? '🇨🇳' : data.market === 'HK_SHARE' ? '🇭🇰' : '🇺🇸'}
          </span>
          <span className="text-xs font-bold text-foreground/90">{data.market_name}</span>
          {!isMarginBalanceMarket && (
            <span className="text-[8px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-500">
              卖空指标
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
          <Clock className="w-2.5 h-2.5" />
          <span className="font-mono tabular-nums">
            {new Date(data.updated_at).toLocaleTimeString('zh-CN', { hour12: false })}
          </span>
        </div>
      </div>

      {/* A 股：两融余额 */}
      {isMarginBalanceMarket && (
        <>
          {/* 融资余额 */}
      <div className="mb-2">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[10px] text-muted-foreground/70">融资余额</span>
          <div className="flex items-center gap-1">
            {financingUp ? (
              <TrendingUp className="w-3 h-3 text-emerald-500" />
            ) : (
              <TrendingDown className="w-3 h-3 text-red-500" />
            )}
            <span
              className={cn(
                'text-xs font-bold font-mono tabular-nums',
                financingUp ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
              )}
            >
              {formatNumber(data.financing_balance)}
              <span className="text-[8px] ml-0.5 opacity-60">{data.unit}</span>
            </span>
          </div>
        </div>
        <div className="flex items-center justify-end">
          <span
            className={cn(
              'text-[9px] font-mono px-1.5 py-0.5 rounded',
              financingUp
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                : 'bg-red-500/10 text-red-600 dark:text-red-400'
            )}
          >
            {formatChange(data.financing_change)} {data.unit}
          </span>
        </div>
      </div>

      {/* 融券余额 */}
      <div>
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[10px] text-muted-foreground/70">融券余额</span>
          <div className="flex items-center gap-1">
            {securitiesUp ? (
              <TrendingUp className="w-3 h-3 text-emerald-500" />
            ) : (
              <TrendingDown className="w-3 h-3 text-red-500" />
            )}
            <span
              className={cn(
                'text-xs font-bold font-mono tabular-nums',
                securitiesUp ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
              )}
            >
              {formatNumber(data.securities_balance)}
              <span className="text-[8px] ml-0.5 opacity-60">{data.unit}</span>
            </span>
          </div>
        </div>
        <div className="flex items-center justify-end">
          <span
            className={cn(
              'text-[9px] font-mono px-1.5 py-0.5 rounded',
              securitiesUp
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                : 'bg-red-500/10 text-red-600 dark:text-red-400'
            )}
          >
            {formatChange(data.securities_change)} {data.unit}
          </span>
        </div>
      </div>
        </>
      )}

      {/* 港股/美股：卖空指标口径（与 A 股两融余额概念不同，如实分列） */}
      {!isMarginBalanceMarket && hasShortMetrics && (
        <>
          {data.short_volume_ratio != null && (
            <div className="mb-1.5">
              <div className="flex items-center justify-between mb-0.5">
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  做空成交占比
                  <span className="text-[7px] px-1 rounded bg-slate-500/15 text-slate-400">{srcLabel('ratio')}</span>
                </span>
                <span className="text-xs font-bold font-mono tabular-nums text-orange-500">
                  {formatRatio(data.short_volume_ratio)}
                </span>
              </div>
            </div>
          )}
          {data.short_interest_shares != null && (
            <div className="mb-1.5">
              <div className="flex items-center justify-between mb-0.5">
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  卖空余额
                  <span className="text-[7px] px-1 rounded bg-slate-500/15 text-slate-400">{srcLabel('interest')}</span>
                </span>
                <span className="text-xs font-bold font-mono tabular-nums text-foreground/90">
                  {formatShares(data.short_interest_shares)}
                </span>
              </div>
            </div>
          )}
          {data.short_interest_ratio != null && (
            <div>
              <div className="flex items-center justify-between mb-0.5">
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  回补天数 (Days to Cover)
                  <span className="text-[7px] px-1 rounded bg-slate-500/15 text-slate-400">{srcLabel('interest')}</span>
                </span>
                <span className="text-xs font-bold font-mono tabular-nums text-foreground/90">
                  {data.short_interest_ratio.toFixed(2)} 天
                </span>
              </div>
            </div>
          )}
        </>
      )}

      {/* 数据来源 */}
      <div className="mt-2 pt-1.5 border-t border-border/10">
        <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
          <span className="inline-block w-1 h-1 rounded-full bg-emerald-400/60"></span>
          <span>{data.source}</span>
        </div>
        {data.note && (
          <div className="flex items-center gap-1 mt-0.5 text-[8px] text-amber-500/70">
            <AlertTriangle className="w-2.5 h-2.5" />
            <span>{data.note}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// 过滤掉「无任何有效数据」的市场卡片。
// - A 股：需融资/融券余额任一有效（两融口径）；
// - 港股/美股：无「融资融券余额」概念，只要任一卖空指标（做空占比/做空余额/回补天数/做空成交量）有效即展示；
// 拿不到就不展示空壳卡，避免误导 —— PROD 红线：零幻觉、不编造
function hasValidBalance(m: MarginMarketData): boolean {
  const valid = (n: number | null | undefined) => n != null && !Number.isNaN(n)
  const f = m.financing_balance
  const s = m.securities_balance
  const hasMarginBalance = valid(f) || valid(s)
  const hasShortMetrics =
    valid(m.short_sale_volume) ||
    valid(m.short_volume_ratio) ||
    valid(m.short_interest_shares) ||
    valid(m.short_interest_ratio)
  // A 股必须靠两融余额；港股/美股靠卖空指标
  if (m.market === 'A_SHARE') return hasMarginBalance
  return hasShortMetrics
}

export function MarginTradingPanel({ data, status, lastUpdated }: MarginTradingPanelProps) {
  const visibleData = (data || []).filter(hasValidBalance)
  if (visibleData.length === 0) {
    return (
      <div className="glass-panel p-4 rounded-xl border border-border/20">
        <div className="flex items-center justify-center gap-2 text-muted-foreground/50">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-xs">暂无融资融券数据</span>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* 面板标题 — 卖空区汇总（A 股两融 / 港股 HKEX 卖空 / 美股 FINRA，做空口径三市场并存） */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-foreground/90">卖空区指标</h3>
          {status === 'partial' && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
              部分数据
            </span>
          )}
        </div>
        {lastUpdated && (
          <div className="flex items-center gap-1 text-[9px] text-muted-foreground/50">
            <Clock className="w-3 h-3" />
            <span>更新于 {formatUpdatedAt(lastUpdated)}</span>
          </div>
        )}
      </div>

      {/* 市场卡片网格 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {visibleData.map((market) => (
          <MarketMarginCard key={market.market} data={market} />
        ))}
      </div>
    </div>
  )
}
