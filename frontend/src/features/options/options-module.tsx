import { useEffect, useState } from 'react'
import { useMarketStore } from '@/stores/marketStore'
import { OptionVolSurface } from './option-vol-surface'

export function OptionsModule() {
  const currentTicker = useMarketStore((s) => s.currentTicker)
  const [symbol, setSymbol] = useState(currentTicker)

  useEffect(() => {
    setSymbol(currentTicker)
  }, [currentTicker])

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">期权隐含波动率曲面</h1>
          <p className="text-xs text-slate-400">
            IV 微笑 + 期限结构热力图 · 行=行权价，列=到期日 · 绿低红高
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">标的</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.trim().toUpperCase())}
            placeholder="如 AAPL / US.AAPL"
            className="w-40 rounded-lg border border-border/60 bg-card px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-primary/60"
          />
        </div>
      </div>

      <div className="glass-card flex-1 overflow-auto rounded-xl border border-border/40 p-4">
        {symbol ? (
          <OptionVolSurface symbol={symbol} />
        ) : (
          <div className="p-6 text-sm text-slate-400">请输入标的代码</div>
        )}
      </div>
    </div>
  )
}
