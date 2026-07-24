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
}

interface MarginTradingPanelProps {
  data: MarginMarketData[]
  status?: string
  lastUpdated?: string
}

function MarketMarginCard({ data }: { data: MarginMarketData }) {
  const financingUp = data.financing_change >= 0
  const securitiesUp = data.securities_change >= 0

  // 格式化数字显示
  const formatNumber = (num: number) => {
    return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  // 格式化变化量
  const formatChange = (num: number) => {
    const sign = num >= 0 ? '+' : ''
    return `${sign}${num.toFixed(2)}`
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
        </div>
        <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
          <Clock className="w-2.5 h-2.5" />
          <span className="font-mono tabular-nums">
            {new Date(data.updated_at).toLocaleTimeString('zh-CN', { hour12: false })}
          </span>
        </div>
      </div>

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

export function MarginTradingPanel({ data, status, lastUpdated }: MarginTradingPanelProps) {
  if (!data || data.length === 0) {
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
      {/* 面板标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-foreground/90">融资融券余额</h3>
          {status === 'partial' && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
              部分数据
            </span>
          )}
        </div>
        {lastUpdated && (
          <div className="flex items-center gap-1 text-[9px] text-muted-foreground/50">
            <Clock className="w-3 h-3" />
            <span>更新于 {new Date(lastUpdated).toLocaleTimeString('zh-CN', { hour12: false })}</span>
          </div>
        )}
      </div>

      {/* 市场卡片网格 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {data.map((market) => (
          <MarketMarginCard key={market.market} data={market} />
        ))}
      </div>
    </div>
  )
}
