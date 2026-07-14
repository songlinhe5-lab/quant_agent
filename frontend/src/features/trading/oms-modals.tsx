import React, { useState } from 'react'
import { GitPullRequest, X, ListOrdered } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import type { ActiveOrder } from './oms-types'

export function AlgoOrderModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast()
  const [algoType, setAlgoType] = useState('TWAP')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('BUY')
  const [qty, setQty] = useState('')
  const [duration, setDuration] = useState('60')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!symbol || !qty || Number(qty) <= 0) {
      toast({ variant: 'destructive', title: '验证失败', description: '请填写正确的标的代码和数量' })
      return
    }
    setIsSubmitting(true)
    try {
      await apiClient.post('/oms/algo/start', {
        algo_type: algoType,
        symbol: symbol.toUpperCase(),
        side,
        target_qty: Number(qty),
        duration_minutes: Number(duration),
      })
      toast({ title: '算法单已下发', description: `成功启动 ${algoType} 拆单任务` })
      onClose()
    } catch (error: any) {
      toast({ variant: 'destructive', title: '下发失败', description: error.message || '网络异常' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-md bg-card border border-border/50 rounded-xl shadow-2xl flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
          <h3 className="text-sm font-bold flex items-center gap-2"><GitPullRequest className="w-4 h-4 text-indigo-500" /> 新建算法拆单任务</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/50 transition-colors"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">算法类型 (Algo Type)</label>
              <select value={algoType} onChange={e => setAlgoType(e.target.value)} className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary">
                <option value="TWAP">TWAP (时间加权)</option>
                <option value="VWAP">VWAP (成交量加权)</option>
                <option value="ICEBERG">Iceberg (冰山委托)</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">标的代码 (Symbol)</label>
              <input type="text" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="如: US.AAPL" className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono uppercase" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">买卖方向 (Side)</label>
              <div className="flex bg-background border border-border/50 rounded-md p-1">
                <button onClick={() => setSide('BUY')} className={cn('flex-1 text-xs py-1.5 rounded transition-colors font-bold', side === 'BUY' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground hover:bg-secondary/50')}>买入 BUY</button>
                <button onClick={() => setSide('SELL')} className={cn('flex-1 text-xs py-1.5 rounded transition-colors font-bold', side === 'SELL' ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'text-muted-foreground hover:bg-secondary/50')}>卖出 SELL</button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">目标数量 (Target Qty)</label>
              <input type="number" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono tabular-nums" />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted-foreground font-medium">执行时长 ({algoType === 'ICEBERG' ? '单笔可见数量' : '分钟'})</label>
            <input type="number" value={duration} onChange={e => setDuration(e.target.value)} className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono tabular-nums" />
          </div>
        </div>
        <div className="px-4 py-3 border-t border-border/30 bg-secondary/10 flex justify-end gap-2 shrink-0">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 text-xs">取消</Button>
          <Button size="sm" className="h-8 text-xs bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm" onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? '下发中...' : '提交执行'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function OrderDetailModal({ order, onClose }: { order: ActiveOrder; onClose: () => void }) {
  const { toast } = useToast()
  const [newPrice, setNewPrice] = useState(order.price)
  const [isModifying, setIsModifying] = useState(false)

  const handleModify = async () => {
    if (!newPrice || isNaN(Number(newPrice))) {
      toast({ variant: 'destructive', title: '验证失败', description: '请输入有效的修改价格' })
      return
    }
    setIsModifying(true)
    try {
      await apiClient.post(`/oms/orders/${order.id}/modify`, { price: Number(newPrice) })
      toast({ title: '改单指令已下发', description: `订单 ${order.id} 价格更新为 ${newPrice}` })
      onClose()
    } catch (error: any) {
      toast({ variant: 'destructive', title: '改单失败', description: error.message || '网络或接口异常' })
    } finally {
      setIsModifying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-sm bg-card border border-border/50 rounded-xl shadow-2xl flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
          <h3 className="text-sm font-bold flex items-center gap-2"><ListOrdered className="w-4 h-4 text-indigo-500" /> 订单详情</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/50 transition-colors"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="flex justify-between items-center pb-3 border-b border-border/20">
            <span className="text-2xl font-bold font-mono">{order.symbol}</span>
            <span className={cn('px-2 py-1 rounded font-bold text-xs', order.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
              {order.side}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-y-4 gap-x-6">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">订单号 (Order ID)</span>
              <span className="text-sm font-mono break-all">{order.id}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">状态 (Status)</span>
              <span className="text-sm font-bold">{order.status}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">委托价 (Price)</span>
              <span className="text-sm font-mono">{order.price}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">委托量/已成交</span>
              <span className="text-sm font-mono">{order.qty} / {order.filled}</span>
            </div>
            <div className="flex flex-col gap-1 col-span-2">
              <span className="text-[10px] text-muted-foreground uppercase">下发时间 (Time)</span>
              <span className="text-sm font-mono">{order.time}</span>
            </div>
            <div className="flex flex-col gap-2 col-span-2 mt-2 pt-4 border-t border-border/20">
              <span className="text-[10px] text-muted-foreground uppercase">修改挂单价格 (Modify Price)</span>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={newPrice}
                  onChange={e => setNewPrice(e.target.value)}
                  className="flex-1 bg-background border border-border/50 rounded-md px-3 py-1.5 text-sm outline-none focus:border-primary font-mono tabular-nums"
                />
                <Button
                  size="sm"
                  onClick={handleModify}
                  disabled={isModifying || String(newPrice) === String(order.price)}
                  className="h-8 text-xs bg-amber-500/10 text-amber-600 dark:text-amber-500 border border-amber-500/20 hover:bg-amber-500/20 shadow-none font-bold"
                >
                  {isModifying ? '提交中...' : '确认改单'}
                </Button>
              </div>
            </div>
          </div>
        </div>
        <div className="px-4 py-3 border-t border-border/30 bg-secondary/10 flex justify-end shrink-0">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 text-xs">关闭</Button>
        </div>
      </div>
    </div>
  )
}
