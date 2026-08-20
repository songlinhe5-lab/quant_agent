import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface OrderBookRow {
  price: number
  size: number
  [k: string]: unknown
}

interface OrderBookData {
  ticker?: string
  bids?: OrderBookRow[]
  asks?: OrderBookRow[]
  best_bid?: number
  best_ask?: number
  spread?: number
  imbalance?: number
  updated_at?: string
  source?: string
  note?: string
}

function priceTone(side: 'bid' | 'ask'): string {
  return side === 'bid' ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]'
}

export function OrderBookPanel({ ticker = 'HK.00700' }: { ticker?: string }) {
  const [data, setData] = useState<OrderBookData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: OrderBookData }>(`/market/order-book?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载盘口深度 ({ticker})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        盘口数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data || (!data.bids?.length && !data.asks?.length)) return <div className="p-6 text-sm text-slate-400">暂无盘口数据</div>

  const bids = (data.bids || []).slice(0, 5)
  const asks = (data.asks || []).slice(0, 5)
  const maxSize = Math.max(
    ...bids.map((b) => b.size || 0),
    ...asks.map((a) => a.size || 0),
    1,
  )

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">L2 盘口深度 (Futu)</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker}</span>
        {data.spread != null && (
          <span className="ml-auto text-[10px] font-mono text-[hsl(var(--ai))]">价差 {data.spread}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 p-3">
        {/* 卖盘（倒序显示，最优卖价贴近中间） */}
        <div className="space-y-1">
          <div className="text-[9px] text-[hsl(var(--bear))] font-semibold mb-0.5">卖盘 ASK</div>
          {[...asks].reverse().map((a, i) => (
            <div key={'a' + i} className="relative flex items-center justify-between px-2 py-1 rounded text-[11px] bg-[hsl(var(--bear))]/5">
              <div className="absolute left-0 top-0 bottom-0 bg-[hsl(var(--bear))]/10" style={{ width: `${((a.size || 0) / maxSize) * 100}%` }} />
              <span className={'relative font-mono ' + priceTone('ask')}>{a.price?.toFixed(2)}</span>
              <span className="relative font-mono text-slate-400">{a.size}</span>
            </div>
          ))}
        </div>
        {/* 买盘 */}
        <div className="space-y-1">
          <div className="text-[9px] text-[hsl(var(--bull))] font-semibold mb-0.5">买盘 BID</div>
          {bids.map((b, i) => (
            <div key={'b' + i} className="relative flex items-center justify-between px-2 py-1 rounded text-[11px] bg-[hsl(var(--bull))]/5">
              <div className="absolute left-0 top-0 bottom-0 bg-[hsl(var(--bull))]/10" style={{ width: `${((b.size || 0) / maxSize) * 100}%` }} />
              <span className={'relative font-mono ' + priceTone('bid')}>{b.price?.toFixed(2)}</span>
              <span className="relative font-mono text-slate-400">{b.size}</span>
            </div>
          ))}
        </div>
      </div>
      {data.imbalance != null && (
        <div className="px-3 pb-2 text-[10px] font-mono text-slate-400">
          买卖盘量比 (Bid/Ask): <span className={data.imbalance >= 1 ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]'}>{data.imbalance.toFixed(2)}</span>
          {data.imbalance >= 1.5 ? ' · 买盘主导' : data.imbalance <= 0.67 ? ' · 卖盘压制' : ' · 均衡'}
        </div>
      )}
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 实时盘口'} · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
