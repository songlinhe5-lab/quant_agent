'use client'

import { useState, useEffect, useRef } from 'react'
import { TrendingUp, TrendingDown, Minus, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MOCK_ASSET_TRENDS, type AssetTrendItem } from '@/services/mock'

// ── 单张资产卡片 ────────────────────────────────────────────────────────────
function AssetCard({ item }: { item: AssetTrendItem }) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const flashTimer = useRef<NodeJS.Timeout | null>(null)
  const prevPrice = useRef(item.price)

  useEffect(() => {
    if (item.price !== prevPrice.current) {
      // 1. 打断并重置当前动画，清理遗留定时器
      setFlash(null)
      if (flashTimer.current) clearTimeout(flashTimer.current)
      
      const direction = item.price > prevPrice.current ? 'up' : 'down'
      prevPrice.current = item.price

      // 2. 延迟 10ms 强制浏览器触发 DOM 重绘并重启 CSS 动画
      setTimeout(() => {
        setFlash(direction)
        flashTimer.current = setTimeout(() => setFlash(null), 800)
      }, 10)
    }
    return () => { if (flashTimer.current) clearTimeout(flashTimer.current) }
  }, [item.price])

  const isUp = item.changePct >= 0
  const TrendIcon = isUp ? TrendingUp : item.changePct < -0.01 ? TrendingDown : Minus
  const trendColor = isUp
    ? 'text-emerald-400'
    : item.changePct < -0.01
      ? 'text-red-400'
      : 'text-amber-400'

  return (
    <div
      className={cn(
        'relative glass-panel rounded-xl p-4 flex-shrink-0 w-[200px] overflow-hidden',
        'border border-border/30 hover:border-border/60',
        'transition-all duration-300 hover:shadow-lg hover:shadow-primary/5',
        'group cursor-default select-none',
        flash === 'up' && 'animate-flash-green',
        flash === 'down' && 'animate-flash-red',
      )}
    >
      {/* 资产类别标签 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
          {item.category}
        </span>
        <span
          className={cn(
            'text-xs font-mono font-semibold tracking-tight',
            trendColor,
          )}
        >
          {item.symbol}
        </span>
      </div>

      {/* 名称 */}
      <div className="text-sm font-semibold text-foreground/90 mb-1 truncate">
        {item.name}
      </div>

      {/* 价格 + 闪光 */}
      <div className="flex items-baseline gap-1.5 mb-2">
        <span
          className={cn(
            'text-xl font-bold font-mono tabular-nums tracking-tight transition-colors duration-500',
            flash === 'up'
              ? 'text-emerald-400'
              : flash === 'down'
                ? 'text-red-400'
                : 'text-foreground',
          )}
        >
          {item.price.toLocaleString('en-US', {
            minimumFractionDigits: item.price >= 1000 ? 0 : 2,
            maximumFractionDigits: item.price >= 1000 ? 0 : 2,
          })}
        </span>
        {item.unit && (
          <span className="text-[10px] text-muted-foreground">{item.unit}</span>
        )}
      </div>

      {/* 涨跌幅 + 方向图标 */}
      <div className="flex items-center gap-1.5">
        <div
          className={cn(
            'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-mono font-semibold tabular-nums',
            isUp
              ? 'bg-emerald-500/10 text-emerald-400'
              : item.changePct < -0.01
                ? 'bg-red-500/10 text-red-400'
                : 'bg-amber-500/10 text-amber-400',
          )}
        >
          <TrendIcon className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
          <span>
            {item.changePct >= 0 ? '+' : ''}
            {item.changePct.toFixed(2)}%
          </span>
        </div>

        {/* Sparkline 微图 */}
        <MiniSpark dirs={item.sparkDirs} isUp={isUp} />
      </div>

      {/* 底部副标题信息 */}
      {item.subtitle && (
        <div className="mt-2 pt-2 border-t border-border/20">
          <div className="flex justify-between text-[10px]">
            <span className="text-muted-foreground">
              {item.subtitle.label}
            </span>
            <span
              className={cn(
                'font-mono tabular-nums font-medium',
                item.subtitle.dir > 0
                  ? 'text-emerald-400'
                  : item.subtitle.dir < 0
                    ? 'text-red-400'
                    : 'text-muted-foreground',
              )}
            >
              {item.subtitle.dir > 0 ? '+' : ''}
              {item.subtitle.value}
            </span>
          </div>
        </div>
      )}

      {/* 悬浮行情解读遮罩 (Hover Tooltip Overlay) */}
      {item.desc30d && (
        <div className="absolute inset-0 z-10 bg-background/95 dark:bg-slate-900/95 backdrop-blur-md p-4 flex flex-col justify-center opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-4 group-hover:translate-y-0">
          <div className="flex items-center gap-1.5 text-xs font-bold text-foreground mb-2">
            <Clock className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            30天行情速览
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {item.desc30d}
          </p>
        </div>
      )}
    </div>
  )
}

// ── 迷你趋势线 SVG ──────────────────────────────────────────────────────────
function MiniSpark({
  dirs,
  isUp,
}: {
  dirs: number[]
  isUp: boolean
}) {
  const w = 56,
    h = 18,
    padding = 2
  const points = dirs.reduce<{ x: number; y: number }[]>(
    (acc, d, i) => {
      const prevY = acc.length > 0 ? acc[acc.length - 1].y : h / 2
      const newY = Math.max(
        padding,
        Math.min(h - padding, prevY - d * 2.2),
      )
      acc.push({
        x: (i / (dirs.length - 1)) * (w - padding * 2) + padding,
        y: newY,
      })
      return acc
    },
    [],
  )

  const strokeColor = isUp
    ? 'rgb(52,211,153)'
    : 'rgb(248,113,113)'
  const fillColor = isUp
    ? 'rgba(52,211,153,0.12)'
    : 'rgba(248,113,113,0.12)'

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ')
  const areaPath =
    linePath +
    ` L${points[points.length - 1].x.toFixed(1)},${h - padding} L${points[0].x.toFixed(1)},${h - padding} Z`

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-hidden="true"
      className="flex-shrink-0 ml-auto opacity-70 group-hover:opacity-100 transition-opacity"
    >
      <path d={areaPath} fill={fillColor} />
      <path
        d={linePath}
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// ── 大类资产走势卡片容器 ─────────────────────────────────────────────────────
export function AssetTrendCards({ initialData }: { initialData?: AssetTrendItem[] }) {
  const [items, setItems] = useState<AssetTrendItem[]>(initialData || MOCK_ASSET_TRENDS)

  // 1. 监听外部父组件传入的数据（例如 REST API 定时全量刷新）
  useEffect(() => {
    if (initialData && initialData.length > 0) {
      setItems(initialData)
    }
  }, [initialData])

  // 2. 监听底层 WebSocket 高频行情增量推送
  useEffect(() => {
    const handleTick = (e: Event) => {
      const { ticker, last_price } = (e as CustomEvent).detail
      if (!ticker || !last_price) return

      setItems((prev) =>
        prev.map((item) => {
          // 如果推送的 ticker 匹配当前卡片的标的 (兼容纯字符和带后缀的模式)
          if (ticker === item.symbol || ticker.includes(item.symbol)) {
            const newPrice = parseFloat(last_price)
            if (isNaN(newPrice)) return item
            
            // 基于新价格重算涨跌幅
            const newChangePct = ((newPrice - item.basePrice) / item.basePrice) * 100
            return { ...item, price: newPrice, changePct: newChangePct }
          }
          return item
        })
      )
    }

    window.addEventListener('market_tick', handleTick)
    return () => window.removeEventListener('market_tick', handleTick)
  }, [])

  return (
    <div className="w-full overflow-x-auto scrollbar-thin">
      <div className="flex gap-3 pb-1 min-w-max px-0.5">
        {items.map((item, idx) => (
          <AssetCard key={item.symbol ?? idx} item={item} />
        ))}
      </div>

      {/* 闪动动画 keyframes */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
          @keyframes flash-green-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); }
            30% { box-shadow: 0 0 14px 3px rgba(52,211,153,0.35); }
          }
          @keyframes flash-red-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(248,113,113,0); }
            30% { box-shadow: 0 0 14px 3px rgba(248,113,113,0.35); }
          }
          .animate-flash-green {
            animation: flash-green-pulse 0.8s ease-out;
          }
          .animate-flash-red {
            animation: flash-red-pulse 0.8s ease-out;
          }
        `,
        }}
      />
    </div>
  )
}