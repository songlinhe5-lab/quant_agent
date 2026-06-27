"use client"

import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Wallet, BarChart3, PieChart, Activity } from "lucide-react"

interface PortfolioSummaryProps {
  totalValue: number
  totalPnl: number
  totalPnlPercent: number
  dayPnl: number
  dayPnlPercent: number
  availableBalance: number
  marginUsed: number
}

export function PortfolioSummary({
  totalValue,
  totalPnl,
  totalPnlPercent,
  dayPnl,
  dayPnlPercent,
  availableBalance,
  marginUsed,
}: PortfolioSummaryProps) {
  const marginRatio = (marginUsed / totalValue) * 100
  const isMarginWarning = marginRatio > 70
  const isMarginDanger = marginRatio > 85

  const stats = [
    {
      label: "总资产",
      value: `$${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      icon: Wallet,
      color: "text-foreground",
    },
    {
      label: "总盈亏",
      value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      subValue: `${totalPnlPercent >= 0 ? "+" : ""}${totalPnlPercent.toFixed(2)}%`,
      icon: totalPnl >= 0 ? TrendingUp : TrendingDown,
      color: totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
    },
    {
      label: "今日盈亏",
      value: `${dayPnl >= 0 ? "+" : ""}$${dayPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      subValue: `${dayPnlPercent >= 0 ? "+" : ""}${dayPnlPercent.toFixed(2)}%`,
      icon: dayPnl >= 0 ? TrendingUp : TrendingDown,
      color: dayPnl >= 0 ? "text-emerald-400" : "text-red-400",
    },
    {
      label: "可用余额",
      value: `$${availableBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      icon: BarChart3,
      color: "text-foreground",
    },
  ]

  return (
    <div className="glass-card rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold flex items-center gap-2">
          <PieChart className="h-4 w-4 text-primary" aria-hidden="true" />
          投资组合
        </h3>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Activity className="h-3 w-3" aria-hidden="true" />
          实时更新
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {stats.map((stat) => (
          <div key={stat.label} className="space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <stat.icon className="h-3 w-3" aria-hidden="true" />
              {stat.label}
            </div>
            <div className={cn("font-mono font-semibold", stat.color)}>
              {stat.value}
            </div>
            {stat.subValue && (
              <div className={cn("text-xs font-mono", stat.color)}>
                {stat.subValue}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Margin Usage Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">保证金使用率</span>
          <span className={cn(
            "font-mono font-medium",
            isMarginDanger ? "text-red-400" : isMarginWarning ? "text-amber-500" : "text-foreground"
          )}>
            {marginRatio.toFixed(1)}%
          </span>
        </div>
        <div className="h-2 bg-secondary rounded-full overflow-hidden">
          <div 
            className={cn(
              "h-full rounded-full transition-all duration-500",
              isMarginDanger ? "bg-red-400" : isMarginWarning ? "bg-amber-500" : "bg-emerald-400"
            )}
            style={{ width: `${Math.min(marginRatio, 100)}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>已用 ${marginUsed.toLocaleString()}</span>
          <span>总额 ${totalValue.toLocaleString()}</span>
        </div>
      </div>
    </div>
  )
}
