import { useState, useEffect, useMemo } from 'react'
import { Plus, X, Star } from 'lucide-react'
import { MarketSnapshotPanel } from '@/features/data-center/market-snapshot-panel'
import { OrderBookPanel } from '@/features/data-center/order-book-panel'
import { CapitalDistributionPanel } from '@/features/data-center/capital-distribution-panel'
import { AnalystVsFundamentalPanel } from '@/features/data-center/analyst-vs-fundamental-panel'
import { ShortSellingPanel } from '@/features/data-center/short-selling-panel'
import { StockBasicInfoPanel } from '@/features/data-center/stock-basicinfo-panel'
import type { useDashboardData as useDashboardDataType } from '@/features/data-center/use-dashboard-data'

interface Props {
  data: ReturnType<typeof useDashboardDataType>
}

const STORAGE_KEY = 'quant_watchlist_tickers'
const DEFAULT_TICKERS = ['US.AAPL', 'US.NVDA', 'US.TSLA', 'HK.00700', 'HK.09988']

export function WatchlistTab({ data }: Props) {
  const [tickers, setTickers] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [active, setActive] = useState('US.AAPL')

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    const init = saved ? JSON.parse(saved) : DEFAULT_TICKERS
    setTickers(init)
    setActive(init[0] || 'US.AAPL')
  }, [])

  const persist = (next: string[]) => {
    setTickers(next)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }

  const addTicker = () => {
    const v = input.trim().toUpperCase()
    if (!v || !v.includes('.') || tickers.includes(v)) { setInput(''); return }
    persist([...tickers, v])
    setActive(v)
    setInput('')
  }

  const removeTicker = (t: string) => {
    const next = tickers.filter((x) => x !== t)
    persist(next.length ? next : DEFAULT_TICKERS)
    if (active === t) setActive((next.length ? next : DEFAULT_TICKERS)[0])
  }

  const market = useMemo(() => active.split('.')[0], [active])
  const tickerCode = useMemo(() => `${market}.${active.split('.')[1]}`, [active, market])

  return (
    <div className="flex flex-col gap-4">
      {/* 自选管理 */}
      <div className="glass-card p-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Star className="h-4 w-4 text-amber-400" />
          {tickers.map((t) => (
            <span
              key={t}
              className={`group flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-mono border cursor-pointer transition-colors ${
                active === t
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'bg-secondary/20 text-muted-foreground border-border/40 hover:text-foreground'
              }`}
              onClick={() => setActive(t)}
            >
              {t}
              <button
                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-red-400"
                onClick={(e) => { e.stopPropagation(); removeTicker(t) }}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <div className="flex items-center gap-1 ml-auto">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addTicker()}
              placeholder="添加如 US.MSFT"
              className="w-32 px-2 py-1 text-xs rounded-lg bg-secondary/30 border border-border/40 outline-none focus:ring-1 focus:ring-primary"
            />
            <button onClick={addTicker} className="p-1.5 rounded-lg bg-primary/15 text-primary hover:bg-primary/25">
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <MarketSnapshotPanel tickers={tickerCode} />
        <OrderBookPanel ticker={tickerCode} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <CapitalDistributionPanel ticker={tickerCode} />
        <StockBasicInfoPanel market={market} secType="STOCK" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <AnalystVsFundamentalPanel ticker={tickerCode} />
        <ShortSellingPanel ticker={tickerCode} mode="overview" />
      </div>
    </div>
  )
}
