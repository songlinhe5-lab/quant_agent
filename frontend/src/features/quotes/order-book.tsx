"use client"

import { cn } from "@/lib/utils"
import { AlertTriangle } from "lucide-react"

export interface OrderBookEntry {
  price: number
  amount: number
  total: number
}

interface OrderBookProps {
  asks: OrderBookEntry[]
  bids: OrderBookEntry[]
  spread: number
  spreadPercent: number
  isStale?: boolean
}

export function OrderBook({ asks, bids, spread, spreadPercent, isStale = false }: OrderBookProps) {
  const maxAskTotal = Math.max(...asks.map(a => a.total))
  const maxBidTotal = Math.max(...bids.map(b => b.total))

  return (
    <div className={cn("glass-card rounded-lg p-4 h-full", isStale && "stale-data")}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">订单簿</h3>
        {isStale && (
          <span 
            className="text-amber-500 text-xs flex items-center gap-1"
            title="订单簿数据可能已过期"
            aria-label="数据过期警告"
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            STALE
          </span>
        )}
      </div>

      {/* Header */}
      <div className="grid grid-cols-3 text-xs text-muted-foreground mb-2 px-2">
        <span>价格 (USD)</span>
        <span className="text-right">数量</span>
        <span className="text-right">累计</span>
      </div>

      {/* Asks (Sells) - Red */}
      <div className="space-y-0.5 mb-2">
        {asks.slice().reverse().map((ask, i) => (
          <div 
            key={`ask-${i}`}
            className="grid grid-cols-3 text-xs font-mono py-1 px-2 relative rounded-sm overflow-hidden"
          >
            <div 
              className="absolute inset-0 bg-red-400/10"
              style={{ width: `${(ask.total / maxAskTotal) * 100}%`, marginLeft: 'auto' }}
            />
            <span className="relative text-red-400">{ask.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
            <span className="relative text-right text-foreground/80">{ask.amount.toFixed(4)}</span>
            <span className="relative text-right text-muted-foreground">{ask.total.toFixed(4)}</span>
          </div>
        ))}
      </div>

      {/* Spread */}
      <div className="flex items-center justify-center gap-2 py-2 border-y border-border/50 my-2">
        <span className="text-sm font-medium text-muted-foreground">价差</span>
        <span className="font-mono text-sm">${spread.toFixed(2)}</span>
        <span className="text-xs text-muted-foreground">({spreadPercent.toFixed(3)}%)</span>
      </div>

      {/* Bids (Buys) - Green */}
      <div className="space-y-0.5">
        {bids.map((bid, i) => (
          <div 
            key={`bid-${i}`}
            className="grid grid-cols-3 text-xs font-mono py-1 px-2 relative rounded-sm overflow-hidden"
          >
            <div 
              className="absolute inset-0 bg-emerald-400/10"
              style={{ width: `${(bid.total / maxBidTotal) * 100}%` }}
            />
            <span className="relative text-emerald-400">{bid.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
            <span className="relative text-right text-foreground/80">{bid.amount.toFixed(4)}</span>
            <span className="relative text-right text-muted-foreground">{bid.total.toFixed(4)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
