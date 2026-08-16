import { useEffect, useState } from 'react'
import { useMarketStore } from '@/stores/marketStore'
import { OptionVolSurface } from './option-vol-surface'
import { OptionVolSurface3D } from './option-vol-surface-3d'
import { OptionPcrPanel } from './option-pcr-panel'
import { FedWatchPanel } from './fed-watch-panel'
import { OptionStrategyLabPanel } from './option-strategy-lab-panel'

type TabKey = 'heatmap' | 'surface3d' | 'pcr'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'heatmap', label: 'IV 热力图' },
  { key: 'surface3d', label: '3D 曲面' },
  { key: 'pcr', label: 'PCR 情绪' },
]

export function OptionsModule() {
  const currentTicker = useMarketStore((s) => s.currentTicker)
  const [symbol, setSymbol] = useState(currentTicker)
  const [tab, setTab] = useState<TabKey>('heatmap')

  useEffect(() => {
    setSymbol(currentTicker)
  }, [currentTicker])

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">期权隐含波动率曲面</h1>
          <p className="text-xs text-slate-400">
            IV 微笑 + 期限结构 · 热力图/3D 曲面行=行权价列=到期日 · 绿低红高
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

      {/* G5：FedWatch 利率路径面板（Futu FED_WATCH，自包含 fetch） */}
      <FedWatchPanel />

      {/* G4：期权损益实验室（Futu OPTION_STRATEGY，自包含 fetch） */}
      <OptionStrategyLabPanel ticker="US.AAPL" strategyType="STRANGLE" spread={5} />

      <div className="inline-flex w-fit rounded-lg border border-border/60 p-0.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors ' +
              (tab === t.key
                ? 'bg-primary text-primary-foreground'
                : 'text-slate-400 hover:text-slate-200')
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="glass-card flex-1 overflow-auto rounded-xl border border-border/40 p-4">
        {tab === 'heatmap' &&
          (symbol ? (
            <OptionVolSurface symbol={symbol} />
          ) : (
            <div className="p-6 text-sm text-slate-400">请输入标的代码</div>
          ))}
        {tab === 'surface3d' &&
          (symbol ? (
            <OptionVolSurface3D symbol={symbol} />
          ) : (
            <div className="p-6 text-sm text-slate-400">请输入标的代码</div>
          ))}
        {tab === 'pcr' && <OptionPcrPanel />}
      </div>
    </div>
  )
}
