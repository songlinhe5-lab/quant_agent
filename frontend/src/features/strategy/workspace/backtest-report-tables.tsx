import { cn } from '@/lib/utils'
import { TrendingDown } from 'lucide-react'

export function LongestDrawdownsList({ items }: { items: any[] }) {
  return (
    <div className="w-full md:w-64 border border-border/20 rounded-xl bg-background/50 shadow-inner p-3 flex flex-col overflow-hidden shrink-0">
      <h4 className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5 shrink-0">
        <TrendingDown className="h-3.5 w-3.5" /> 最长回撤期 Top 5
      </h4>
      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-1">
        {items?.length > 0 ? (
          items.map((dd: any, idx: number, arr: any[]) => {
            const maxD = Math.max(...arr.map((d) => d.depth))
            const depthPct = maxD > 0 ? (dd.depth / maxD) * 100 : 0
            return (
              <div key={idx} className="bg-secondary/20 p-2 rounded-lg border border-border/30 text-[10px] hover:border-red-500/30 transition-colors">
                <div className="flex justify-between items-center mb-1.5">
                  <span className="font-bold text-foreground flex items-center gap-1">
                    <span className="text-muted-foreground">#{idx + 1}</span> 经历 {dd.duration} 天
                  </span>
                  <span className="text-red-500 font-mono font-bold">-{dd.depth.toFixed(2)}%</span>
                </div>
                <div className="w-full h-1 bg-border/50 rounded-full mb-1.5 overflow-hidden">
                  <div className="h-full bg-red-500/60 rounded-full" style={{ width: `${depthPct}%` }} />
                </div>
                <div className="text-muted-foreground flex justify-between font-mono text-[9px]">
                  <span>{dd.start}</span>
                  <span className="mx-1">→</span>
                  {dd.recovered ? (
                    <span>{dd.end}</span>
                  ) : (
                    <span className="text-red-500 font-bold flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
                      至今未修复
                    </span>
                  )}
                </div>
              </div>
            )
          })
        ) : (
          <div className="text-center text-[10px] text-muted-foreground mt-10">暂无回撤记录</div>
        )}
      </div>
    </div>
  )
}

export function TradesTable({ trades }: { trades: any[] }) {
  if (!trades?.length) {
    return <div className="p-8 text-center text-muted-foreground text-xs">无交易记录</div>
  }
  return (
    <div className="overflow-x-auto custom-scrollbar max-h-64">
      <table className="w-full text-xs text-left">
        <thead className="bg-slate-50/50 dark:bg-black/20 text-muted-foreground sticky top-0 z-10">
          <tr>
            <th className="px-4 py-2 font-medium">日期</th>
            <th className="px-4 py-2 font-medium">方向</th>
            <th className="px-4 py-2 font-medium text-right">成交价</th>
            <th className="px-4 py-2 font-medium text-right">股数</th>
            <th className="px-4 py-2 font-medium text-right">平仓盈亏</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/20">
          {trades.map((trade: any, idx: number, arr: any[]) => {
            let holdingDays = ''
            if (['SELL', 'COVER'].includes(trade.action)) {
              for (let i = idx - 1; i >= 0; i--) {
                if (['BUY', 'SHORT'].includes(arr[i].action)) {
                  const days = Math.max(
                    1,
                    Math.round(
                      (new Date(trade.date).getTime() - new Date(arr[i].date).getTime()) / (1000 * 3600 * 24),
                    ),
                  )
                  holdingDays = `历时 ${days} 天`
                  break
                }
              }
            }
            return (
              <tr key={idx} className="hover:bg-secondary/20 transition-colors">
                <td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground flex items-center">
                  {trade.date}
                  {holdingDays && (
                    <span className="ml-2 text-[9px] text-indigo-400 bg-indigo-500/10 px-1 py-0.5 rounded">{holdingDays}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 font-bold text-[10px]">
                  <span
                    className={cn(
                      'px-1.5 py-0.5 rounded',
                      ['BUY', 'COVER'].includes(trade.action)
                        ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                        : 'bg-red-500/15 text-red-600 dark:text-red-400',
                    )}
                  >
                    {trade.action}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-[11px]">${Number(trade.price).toFixed(2)}</td>
                <td className="px-4 py-2.5 text-right font-mono text-[11px] text-muted-foreground">{trade.shares}</td>
                <td
                  className={cn(
                    'px-4 py-2.5 text-right font-mono text-[11px] font-bold',
                    trade.profit > 0 ? 'text-emerald-500' : trade.profit < 0 ? 'text-red-500' : 'text-muted-foreground',
                  )}
                >
                  {['SELL', 'COVER'].includes(trade.action)
                    ? trade.profit > 0
                      ? `+$${Number(trade.profit).toFixed(2)}`
                      : `-$${Math.abs(Number(trade.profit)).toFixed(2)}`
                    : '-'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function LimitOrdersTable({
  orders,
  selectedIdx,
  onSelect,
}: {
  orders: any[]
  selectedIdx: number | null
  onSelect: (order: any, idx: number) => void
}) {
  if (!orders?.length) {
    return <div className="p-8 text-center text-muted-foreground text-xs">无追踪限价单</div>
  }
  return (
    <div className="overflow-x-auto custom-scrollbar max-h-64">
      <table className="w-full text-xs text-left whitespace-nowrap">
        <thead className="bg-slate-50/50 dark:bg-black/20 text-muted-foreground sticky top-0 z-10">
          <tr>
            <th className="px-4 py-2 font-medium">挂单日</th>
            <th className="px-4 py-2 font-medium">终结日</th>
            <th className="px-4 py-2 font-medium text-right">限价 (Limit)</th>
            <th className="px-4 py-2 font-medium text-center">最终状态</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/20">
          {orders.map((order: any, idx: number) => (
            <tr
              key={idx}
              id={`limit-order-row-${idx}`}
              className={cn(
                'transition-colors cursor-pointer',
                selectedIdx === idx ? 'bg-amber-500/20' : 'hover:bg-secondary/20',
              )}
              onClick={() => onSelect(order, idx)}
            >
              <td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">{order.start_date}</td>
              <td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">{order.end_date}</td>
              <td className="px-4 py-2.5 text-right font-mono text-[11px] font-bold text-amber-500">
                ${Number(order.price).toFixed(2)}
              </td>
              <td className="px-4 py-2.5 text-center">
                <span
                  className={cn(
                    'px-2 py-0.5 rounded text-[10px] font-bold border',
                    order.status === 'FILLED'
                      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                      : order.status === 'CANCELED'
                        ? 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30'
                        : 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
                  )}
                >
                  {order.status === 'FILLED' ? '✅ 成交' : order.status === 'CANCELED' ? '❌ 撤单' : '⏳ 挂起'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
