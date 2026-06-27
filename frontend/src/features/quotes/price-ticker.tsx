"use client"

import { useState, useEffect, useCallback } from "react"
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"

export interface TickerData {
  symbol: string
  price: number
  change: number
  changePercent: number
  volume: string
  high24h: number
  low24h: number
  isStale?: boolean
  lastUpdate?: number
}

interface PriceTickerProps {
  data: TickerData
  showVolume?: boolean
  compact?: boolean
}

export function PriceTicker({ data, showVolume = true, compact = false }: PriceTickerProps) {
  const [flashClass, setFlashClass] = useState("")
  const [prevPrice, setPrevPrice] = useState(data.price)

  useEffect(() => {
    if (data.price !== prevPrice) {
      const direction = data.price > prevPrice ? "tick-up" : "tick-down"
      setFlashClass(direction)
      setPrevPrice(data.price)
      const timer = setTimeout(() => setFlashClass(""), 400)
      return () => clearTimeout(timer)
    }
  }, [data.price, prevPrice])

  const isPositive = data.change >= 0
  const ColorClass = isPositive ? "text-emerald-400" : "text-red-400"
  const Icon = data.change === 0 ? Minus : isPositive ? TrendingUp : TrendingDown

  if (compact) {
    return (
      <div
        className={cn(
          "flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-300",
          flashClass,
          data.isStale && "stale-data"
        )}
      >
        <span className="font-mono text-sm text-muted-foreground">{data.symbol}</span>
        <span className="font-mono text-sm font-medium">${data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        <span className={cn("font-mono text-xs flex items-center gap-1", ColorClass)}>
          <Icon className="h-3 w-3" aria-hidden="true" />
          {isPositive ? "+" : ""}{data.changePercent.toFixed(2)}%
        </span>
        {data.isStale && (
          <span 
            className="text-amber-500 text-xs flex items-center gap-1"
            title="数据可能已过期"
            aria-label="数据过期警告"
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            STALE
          </span>
        )}
      </div>
    )
  }

  return (
    <div
      className={cn(
        "glass-card rounded-lg p-4 transition-all duration-300",
        flashClass,
        data.isStale && "stale-data"
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-semibold text-lg">{data.symbol}</h3>
          {data.isStale && (
            <span 
              className="text-amber-500 text-xs flex items-center gap-1 mt-1"
              title="数据可能已过期，网络连接中断"
              aria-label="数据过期警告"
            >
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              数据延迟
            </span>
          )}
        </div>
        <div className={cn("flex items-center gap-1 px-2 py-1 rounded text-xs font-medium", 
          isPositive ? "bg-emerald-400/10 text-emerald-400" : "bg-red-400/10 text-red-400"
        )}>
          <Icon className="h-3 w-3" aria-hidden="true" />
          {isPositive ? "+" : ""}{data.changePercent.toFixed(2)}%
        </div>
      </div>
      
      <div className="space-y-2">
        <div className="font-mono text-2xl font-bold">
          ${data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        
        <div className={cn("font-mono text-sm", ColorClass)}>
          {isPositive ? "+" : ""}${data.change.toFixed(2)}
        </div>

        {showVolume && (
          <div className="flex justify-between text-xs text-muted-foreground pt-2 border-t border-border/50">
            <span>成交量 {data.volume}</span>
            <span>24h: ${data.low24h.toLocaleString()} - ${data.high24h.toLocaleString()}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// Hook for simulating real-time price updates
export function usePriceData(initialData: TickerData[]) {
  const [data, setData] = useState(initialData)
  const [isConnected, setIsConnected] = useState(true)

  const simulateUpdate = useCallback(() => {
    if (!isConnected) return
    
    setData(prev => prev.map(ticker => {
      const changePercent = (Math.random() - 0.5) * 0.5
      const newPrice = ticker.price * (1 + changePercent / 100)
      const newChange = newPrice - (ticker.price - ticker.change)
      const newChangePercent = (newChange / (ticker.price - ticker.change)) * 100
      
      return {
        ...ticker,
        price: newPrice,
        change: newChange,
        changePercent: newChangePercent,
        lastUpdate: Date.now(),
        isStale: false,
      }
    }))
  }, [isConnected])

  // Mark data as stale when disconnected
  useEffect(() => {
    if (!isConnected) {
      const staleTimer = setTimeout(() => {
        setData(prev => prev.map(ticker => ({ ...ticker, isStale: true })))
      }, 5000)
      return () => clearTimeout(staleTimer)
    }
  }, [isConnected])

  useEffect(() => {
    const interval = setInterval(simulateUpdate, 1500)
    return () => clearInterval(interval)
  }, [simulateUpdate])

  return { data, isConnected, setIsConnected }
}
