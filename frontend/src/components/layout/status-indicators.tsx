"use client"

import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"
import { Wifi, WifiOff, Activity, Clock, AlertTriangle, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ConnectionStatusProps {
  isConnected: boolean
  latency?: number
  lastUpdate?: Date
  onReconnect?: () => void
}

export function ConnectionStatus({ isConnected, latency = 0, lastUpdate, onReconnect }: ConnectionStatusProps) {
  const [mounted, setMounted] = useState(false)
  
  useEffect(() => {
    setMounted(true)
  }, [])

  const formattedTime = mounted && lastUpdate 
    ? lastUpdate.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "--:--:--"

  return (
    <div className="flex items-center gap-4">
      {/* Connection Indicator */}
      <div 
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium",
          isConnected 
            ? "bg-emerald-400/10 text-emerald-400" 
            : "bg-red-400/10 text-red-400"
        )}
        title={isConnected ? "WebSocket 连接正常" : "WebSocket 连接中断"}
        aria-label={isConnected ? "连接状态：正常" : "连接状态：已断开"}
      >
        {isConnected ? (
          <>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400 status-online"></span>
            </span>
            <Wifi className="h-3 w-3" aria-hidden="true" />
            <span>实时</span>
          </>
        ) : (
          <>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-400 status-offline"></span>
            <WifiOff className="h-3 w-3" aria-hidden="true" />
            <span>断开</span>
          </>
        )}
      </div>

      {/* Latency */}
      {isConnected && (
        <div 
          className={cn(
            "flex items-center gap-1.5 text-xs",
            latency < 100 ? "text-emerald-400" : latency < 300 ? "text-amber-500" : "text-red-400"
          )}
          title={`网络延迟: ${latency}ms`}
          aria-label={`网络延迟 ${latency} 毫秒`}
        >
          <Activity className="h-3 w-3" aria-hidden="true" />
          <span className="font-mono">{latency}ms</span>
        </div>
      )}

      {/* Last Update Time */}
      <div 
        className="flex items-center gap-1.5 text-xs text-muted-foreground"
        title="最后更新时间"
        aria-label={`最后更新时间 ${formattedTime}`}
        suppressHydrationWarning
      >
        <Clock className="h-3 w-3" aria-hidden="true" />
        <span className="font-mono" suppressHydrationWarning>{formattedTime}</span>
      </div>

      {/* Reconnect Button */}
      {!isConnected && onReconnect && (
        <Button
          size="sm"
          variant="outline"
          className="h-7 px-2 text-xs gap-1 border-amber-500/50 text-amber-500 hover:bg-amber-500/10"
          onClick={onReconnect}
          title="重新连接"
          aria-label="重新连接 WebSocket"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          重连
        </Button>
      )}
    </div>
  )
}

// Alert Banner for critical warnings
interface AlertBannerProps {
  type: "warning" | "error" | "info"
  message: string
  onDismiss?: () => void
}

export function AlertBanner({ type, message, onDismiss }: AlertBannerProps) {
  const colorMap = {
    warning: "bg-amber-500/10 border-amber-500/30 text-amber-500",
    error: "bg-red-400/10 border-red-400/30 text-red-400",
    info: "bg-blue-400/10 border-blue-400/30 text-blue-400",
  }

  return (
    <div 
      className={cn(
        "flex items-center justify-between gap-3 px-4 py-2 rounded-lg border",
        colorMap[type]
      )}
      role="alert"
      aria-live="polite"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
        <span className="text-sm">{message}</span>
      </div>
      {onDismiss && (
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0 hover:bg-current/10"
          onClick={onDismiss}
          title="关闭提示"
          aria-label="关闭警告提示"
        >
          ×
        </Button>
      )}
    </div>
  )
}

// Market Status Indicator
interface MarketStatusProps {
  isOpen: boolean
  market: string
  nextEvent?: string
}

export function MarketStatus({ isOpen, market, nextEvent }: MarketStatusProps) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <div 
        className={cn(
          "flex items-center gap-1.5 px-2 py-1 rounded",
          isOpen ? "bg-emerald-400/10 text-emerald-400" : "bg-red-400/10 text-red-400"
        )}
        title={isOpen ? `${market} 市场交易中` : `${market} 市场已休市`}
        aria-label={isOpen ? `${market} 市场状态：交易中` : `${market} 市场状态：已休市`}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", isOpen ? "bg-emerald-400" : "bg-red-400")} />
        <span>{market}</span>
        <span>{isOpen ? "交易中" : "休市"}</span>
      </div>
      {nextEvent && (
        <span className="text-muted-foreground">{nextEvent}</span>
      )}
    </div>
  )
}
