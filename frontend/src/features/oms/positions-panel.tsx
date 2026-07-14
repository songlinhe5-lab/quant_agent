"use client"

import { cn } from "@/lib/utils"
import { AlertTriangle, X, CheckCircle2, XCircle, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { VirtualList } from '@/components/virtual-list'
import { DataState, resolveDataStatus } from '@/components/data-state'

export interface Position {
  id: string
  symbol: string
  side: "long" | "short"
  entryPrice: number
  currentPrice: number
  size: number
  leverage: number
  pnl: number
  pnlPercent: number
  liquidationPrice: number
}

interface PositionsPanelProps {
  positions: Position[]
  isStale?: boolean
  onClose?: (id: string) => void
}

export function PositionsPanel({ positions, isStale = false, onClose }: PositionsPanelProps) {
  const totalPnl = positions.reduce((acc, p) => acc + p.pnl, 0)
  const hasRiskPositions = positions.some(p => {
    const riskRatio = p.side === "long" 
      ? (p.currentPrice - p.liquidationPrice) / p.currentPrice
      : (p.liquidationPrice - p.currentPrice) / p.currentPrice
    return riskRatio < 0.1
  })

  const viewStatus = resolveDataStatus({
    empty: positions.length === 0,
    stale: isStale,
  })

  return (
    <div className={cn("glass-card rounded-lg p-4", isStale && "stale-data")}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold">持仓</h3>
          <span className="text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded">
            {positions.length}
          </span>
          {hasRiskPositions && (
            <span 
              className="text-amber-500 text-xs flex items-center gap-1"
              title="部分持仓接近强平价格"
              aria-label="风险警告"
            >
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              风险
            </span>
          )}
        </div>
        <div className={cn(
          "font-mono text-sm font-medium",
          totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
        )}>
          {totalPnl >= 0 ? "+" : ""}{totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2 })} USD
        </div>
        {isStale && (
          <span 
            className="text-amber-500 text-xs flex items-center gap-1"
            title="持仓数据可能已过期"
            aria-label="数据过期警告"
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            STALE
          </span>
        )}
      </div>

      <DataState
        status={viewStatus === 'stale' ? 'ready' : viewStatus}
        emptyTitle="暂无持仓"
        emptyDescription="下单成交后将显示在此处"
      >
        <div className="space-y-2">
          <div className="grid grid-cols-7 gap-2 text-xs text-muted-foreground px-2">
            <span>交易对</span>
            <span className="text-right">方向</span>
            <span className="text-right">数量</span>
            <span className="text-right">入场价</span>
            <span className="text-right">当前价</span>
            <span className="text-right">盈亏</span>
            <span className="text-right">操作</span>
          </div>

          {positions.length > 40 ? (
            <VirtualList
              items={positions}
              estimateSize={40}
              height={Math.min(480, positions.length * 40)}
              getKey={(p) => p.id}
              renderItem={(position) => (
                <PositionRow position={position} onClose={onClose} />
              )}
            />
          ) : (
            positions.map((position) => (
              <PositionRow key={position.id} position={position} onClose={onClose} />
            ))
          )}
        </div>
      </DataState>
    </div>
  )
}

function PositionRow({
  position,
  onClose,
}: {
  position: Position
  onClose?: (id: string) => void
}) {
  const isLong = position.side === 'long'
  const isProfitable = position.pnl >= 0
  const riskRatio = isLong
    ? (position.currentPrice - position.liquidationPrice) / position.currentPrice
    : (position.liquidationPrice - position.currentPrice) / position.currentPrice
  const isHighRisk = riskRatio < 0.1

  return (
    <div
      className={cn(
        'grid grid-cols-7 gap-2 text-xs font-mono py-2 px-2 rounded-md transition-colors duration-base',
        'hover:bg-secondary/50',
        isHighRisk && 'border border-amber-500/30 bg-amber-500/5',
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-foreground">{position.symbol}</span>
        <span className="text-muted-foreground">{position.leverage}x</span>
      </div>
      <div className={cn('text-right', isLong ? 'text-emerald-400' : 'text-red-400')}>
        {isLong ? '多' : '空'}
      </div>
      <div className="text-right text-foreground/80">{position.size.toFixed(4)}</div>
      <div className="text-right text-muted-foreground">
        ${position.entryPrice.toLocaleString(undefined, { minimumFractionDigits: 2 })}
      </div>
      <div className="text-right">
        ${position.currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2 })}
      </div>
      <div className={cn('text-right', isProfitable ? 'text-emerald-400' : 'text-red-400')}>
        {isProfitable ? '+' : ''}
        {position.pnl.toFixed(2)}
        <span className="text-muted-foreground ml-1">({position.pnlPercent.toFixed(2)}%)</span>
      </div>
      <div className="text-right">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0 hover:bg-red-400/10 hover:text-red-400"
          onClick={() => onClose?.(position.id)}
          title={`平仓 ${position.symbol}`}
          aria-label={`平仓 ${position.symbol} 持仓`}
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

// Order History
export interface HistoricalOrder {
  id: string
  symbol: string
  side: "buy" | "sell"
  type: "market" | "limit"
  price: number
  amount: number
  filled: number
  status: "filled" | "cancelled" | "pending"
  time: string
}

interface OrderHistoryProps {
  orders: HistoricalOrder[]
  isStale?: boolean
  onCancel?: (id: string) => void
}

export function OrderHistory({ orders, isStale = false, onCancel }: OrderHistoryProps) {
  const StatusIcon = {
    filled: CheckCircle2,
    cancelled: XCircle,
    pending: Clock,
  }

  const StatusColor = {
    filled: "text-emerald-400",
    cancelled: "text-red-400",
    pending: "text-amber-500",
  }

  const StatusLabel = {
    filled: "已成交",
    cancelled: "已取消",
    pending: "待成交",
  }

  const viewStatus = resolveDataStatus({
    empty: orders.length === 0,
    stale: isStale,
  })

  return (
    <div className={cn("glass-card rounded-lg p-4", isStale && "stale-data")}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">订单历史</h3>
        {isStale && (
          <span 
            className="text-amber-500 text-xs flex items-center gap-1"
            title="订单数据可能已过期"
            aria-label="数据过期警告"
          >
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            STALE
          </span>
        )}
      </div>

      <DataState
        status={viewStatus === 'stale' ? 'ready' : viewStatus}
        emptyTitle="暂无订单记录"
        emptyDescription="委托与成交记录将显示在此处"
      >
        <div className="space-y-2">
          <div className="grid grid-cols-6 gap-2 text-xs text-muted-foreground px-2 sticky top-0 bg-card py-1">
            <span>交易对</span>
            <span className="text-right">方向/类型</span>
            <span className="text-right">价格</span>
            <span className="text-right">数量</span>
            <span className="text-right">状态</span>
            <span className="text-right">时间</span>
          </div>

          {orders.length > 40 ? (
            <VirtualList
              items={orders}
              estimateSize={36}
              height={250}
              getKey={(o) => o.id}
              renderItem={(order) => (
                <OrderHistoryRow
                  order={order}
                  StatusIcon={StatusIcon}
                  StatusColor={StatusColor}
                  StatusLabel={StatusLabel}
                  onCancel={onCancel}
                />
              )}
            />
          ) : (
            <div className="max-h-[250px] overflow-y-auto space-y-0">
              {orders.map((order) => (
                <OrderHistoryRow
                  key={order.id}
                  order={order}
                  StatusIcon={StatusIcon}
                  StatusColor={StatusColor}
                  StatusLabel={StatusLabel}
                  onCancel={onCancel}
                />
              ))}
            </div>
          )}
        </div>
      </DataState>
    </div>
  )
}

function OrderHistoryRow({
  order,
  StatusIcon,
  StatusColor,
  StatusLabel,
  onCancel,
}: {
  order: HistoricalOrder
  StatusIcon: Record<HistoricalOrder['status'], typeof CheckCircle2>
  StatusColor: Record<HistoricalOrder['status'], string>
  StatusLabel: Record<HistoricalOrder['status'], string>
  onCancel?: (id: string) => void
}) {
  const Icon = StatusIcon[order.status]
  return (
    <div className="grid grid-cols-6 gap-2 text-xs font-mono py-2 px-2 rounded-md hover:bg-secondary/50 transition-colors duration-base">
      <span className="text-foreground">{order.symbol}</span>
      <div className="text-right">
        <span className={order.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}>
          {order.side === 'buy' ? '买' : '卖'}
        </span>
        <span className="text-muted-foreground ml-1">
          {order.type === 'limit' ? '限价' : '市价'}
        </span>
      </div>
      <span className="text-right text-muted-foreground">
        ${order.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
      </span>
      <span className="text-right text-foreground/80">
        {order.filled}/{order.amount.toFixed(4)}
      </span>
      <div className={cn('text-right flex items-center justify-end gap-1', StatusColor[order.status])}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        <span>{StatusLabel[order.status]}</span>
        {order.status === 'pending' && (
          <Button
            size="sm"
            variant="ghost"
            className="h-5 w-5 p-0 ml-1 hover:bg-red-400/10 hover:text-red-400"
            onClick={() => onCancel?.(order.id)}
            title="取消订单"
            aria-label={`取消 ${order.symbol} 订单`}
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </Button>
        )}
      </div>
      <span className="text-right text-muted-foreground">{order.time}</span>
    </div>
  )
}
