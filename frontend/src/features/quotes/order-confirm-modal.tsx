import { useEffect, useState } from 'react'
import { X, ArrowUp, ArrowDown, ShieldAlert, Target, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { useTradeStore, type OrderSide, type OrderType } from '@/stores/useTradeStore'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'

/**
 * PROD-09：拖拽设置价格线松手后弹出的下单确认弹窗。
 * 数据为本地沙箱推演（OMS 未实装），仅作可视化确认，不触发真实经纪商下单。
 */
export function OrderConfirmModal() {
  const pending = useTradeStore((s) => s.pending)
  const cancelPending = useTradeStore((s) => s.cancelPending)

  const [side, setSide] = useState<OrderSide>('BUY')
  const [type, setType] = useState<OrderType>('LIMIT')
  const [qty, setQty] = useState<string>('100')
  const [sl, setSl] = useState<string>('')
  const [tp, setTp] = useState<string>('')

  const ai04Enabled = useAiPushPrefStore((s) => s.isEnabled('ai04'))
  const [precheck, setPrecheck] = useState<{
    vix: number | null
    rule_warning: string | null
    llm_advice: { advice?: string; caution?: string; confidence?: number } | null
    message: string | null
  } | null>(null)
  const [precheckLoading, setPrecheckLoading] = useState(false)

  // PROD-09: 每次新草稿进入时重置表单（默认限价买入，用户可在弹窗内调整）
  useEffect(() => {
    if (!pending) return
    setQty('100')
    setSl('')
    setTp('')
    setSide('BUY')
    setType('LIMIT')
  }, [pending])

  // AI-04: 弹窗内参数变化时调用 OMS 执行风控官预检（ai04 开关控制）
  useEffect(() => {
    if (!pending || !ai04Enabled) {
      setPrecheck(null)
      return
    }
    const priceNum = Number(pending.price)
    const qtyNum = Number(qty) || 0
    let alive = true
    setPrecheckLoading(true)
    setPrecheck(null)
    ;(async () => {
      try {
        const res = await apiClient.post('/oms/precheck', {
          symbol: pending.symbol,
          side: side,
          order_type: type,
          price: priceNum,
          qty: qtyNum,
        })
        const body = res.data || res
        if (alive && body) setPrecheck(body)
      } catch (e: any) {
        if (alive) setPrecheck({ vix: null, rule_warning: null, llm_advice: null, message: e?.response?.data?.message || '预检调用失败' })
      } finally {
        if (alive) setPrecheckLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [pending, ai04Enabled, side, type, qty])

  if (!pending) return null

  const priceNum = Number(pending.price)
  const qtyNum = Number(qty) || 0
  const notional = isFinite(priceNum) && isFinite(qtyNum) ? priceNum * qtyNum : 0

  const handleConfirm = () => {
    // 将 SL/TP 随持仓一并落库（沙箱推演，非实盘）
    const id = globalThis.crypto?.randomUUID?.() ?? `pos-${Date.now().toString(36)}`
    useTradeStore.setState((s) => ({
      positions: {
        ...s.positions,
        [pending.symbol]: [
          ...(s.positions[pending.symbol] ?? []),
          {
            id,
            symbol: pending.symbol,
            side,
            entryPrice: priceNum,
            qty: qtyNum,
            sl: sl ? Number(sl) : undefined,
            tp: tp ? Number(tp) : undefined,
            createdAt: Date.now(),
          },
        ],
      },
      pending: null,
    }))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={cancelPending}>
      <div className="w-[360px] bg-popover border border-border rounded-xl shadow-2xl p-4 text-foreground" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-primary" /> 下单确认（沙箱推演）
          </h3>
          <button onClick={cancelPending} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>

        <div className="text-[11px] text-muted-foreground mb-3">
          标的 <span className="font-mono font-semibold text-foreground">{pending.symbol}</span> · 拖拽价位{' '}
          <span className="font-mono font-semibold text-foreground">{priceNum.toFixed(2)}</span>
          <span className="ml-1 text-amber-500">（模拟，非实盘）</span>
        </div>

        <div className="grid grid-cols-2 gap-2 mb-2">
          <button onClick={() => setSide('BUY')} className={cn('h-9 rounded-lg border text-xs font-bold flex items-center justify-center gap-1 transition-colors', side === 'BUY' ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-500' : 'bg-background border-border text-muted-foreground')}>
            <ArrowUp className="h-3.5 w-3.5" /> 买入 BUY
          </button>
          <button onClick={() => setSide('SELL')} className={cn('h-9 rounded-lg border text-xs font-bold flex items-center justify-center gap-1 transition-colors', side === 'SELL' ? 'bg-red-500/15 border-red-500/40 text-red-500' : 'bg-background border-border text-muted-foreground')}>
            <ArrowDown className="h-3.5 w-3.5" /> 卖出 SELL
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2 mb-3">
          <button onClick={() => setType('LIMIT')} className={cn('h-8 rounded-lg border text-[11px] font-semibold transition-colors', type === 'LIMIT' ? 'bg-primary/15 border-primary/40 text-primary' : 'bg-background border-border text-muted-foreground')}>限价 LIMIT</button>
          <button onClick={() => setType('STOP')} className={cn('h-8 rounded-lg border text-[11px] font-semibold transition-colors', type === 'STOP' ? 'bg-primary/15 border-primary/40 text-primary' : 'bg-background border-border text-muted-foreground')}>止损 STOP</button>
        </div>

        <div className="space-y-2 text-[11px]">
          <label className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">委托价</span>
            <input value={priceNum.toFixed(2)} disabled className="w-24 text-right font-mono bg-secondary/40 border border-border rounded px-2 py-1" />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">数量 (股)</span>
            <input value={qty} onChange={(e) => setQty(e.target.value.replace(/[^0-9.]/g, ''))} className="w-24 text-right font-mono bg-background border border-border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary" />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground flex items-center gap-1"><ShieldAlert className="h-3 w-3 text-red-400" /> 止损 SL</span>
            <input value={sl} onChange={(e) => setSl(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="可选" className="w-24 text-right font-mono bg-background border border-border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary" />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground flex items-center gap-1"><Target className="h-3 w-3 text-emerald-400" /> 止盈 TP</span>
            <input value={tp} onChange={(e) => setTp(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="可选" className="w-24 text-right font-mono bg-background border border-border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary" />
          </label>
        </div>

        <div className="flex items-center justify-between mt-3 mb-3 text-[11px] text-muted-foreground">
          <span>预估金额</span>
          <span className="font-mono font-semibold text-foreground">{notional.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
        </div>

        {ai04Enabled && (
          <div className="mb-3 rounded-lg border border-primary/20 bg-primary/5 p-2.5">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              <span className="text-[11px] font-semibold text-primary">AI 执行风控预检</span>
              {precheckLoading && <span className="text-[9px] text-muted-foreground">研判中…</span>}
            </div>
            {precheck?.vix != null && (
              <p className="text-[10px] text-muted-foreground mb-1">
                当前 VIX <span className="font-mono font-semibold text-foreground">{precheck.vix.toFixed(1)}</span>
              </p>
            )}
            {precheck?.rule_warning && (
              <p className="text-[10px] text-red-400 bg-red-500/10 rounded px-1.5 py-1 mb-1">{precheck.rule_warning}</p>
            )}
            {precheck?.llm_advice?.advice && (
              <div className="text-[10px] text-foreground/90 space-y-0.5">
                <p>{precheck.llm_advice.advice}</p>
                {precheck.llm_advice.caution && (
                  <p className="text-amber-500/90">⚠ {precheck.llm_advice.caution}</p>
                )}
                {precheck.llm_advice.confidence != null && (
                  <p className="text-muted-foreground">置信度 {(precheck.llm_advice.confidence * 100).toFixed(0)}%</p>
                )}
              </div>
            )}
            {!precheck && !precheckLoading && (
              <p className="text-[10px] text-muted-foreground">预检暂不可用</p>
            )}
            {precheck?.message && (
              <p className="text-[9px] text-muted-foreground/70 mt-1">{precheck.message}</p>
            )}
            <p className="pt-1 mt-1 text-[9px] text-muted-foreground/50 border-t border-border/30">
              AI 生成 · 仅供参考，不构成投资建议
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <button onClick={cancelPending} className="flex-1 h-9 rounded-lg border border-border text-xs font-semibold text-muted-foreground hover:bg-secondary">取消</button>
          <button onClick={handleConfirm} className="flex-1 h-9 rounded-lg bg-primary text-primary-foreground text-xs font-bold hover:opacity-90">模拟提交</button>
        </div>
      </div>
    </div>
  )
}
