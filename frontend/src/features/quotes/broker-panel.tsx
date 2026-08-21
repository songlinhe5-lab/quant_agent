import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { AlertTriangle } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface BrokerItem {
  broker_name?: string
  avg_price?: number | null
  net_vol?: number | null
  total_vol?: number | null
  total_turnover?: number | null
}

interface TopBrokersResp {
  status: 'success' | 'error' | 'unsupported'
  source?: string
  buy_brokers?: BrokerItem[]
  sell_brokers?: BrokerItem[]
  days_before?: number
  is_real_time?: boolean
  message?: string
}

const fmtVol = (v?: number | null) =>
  v == null ? '—' : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : v.toFixed(0)
const fmtMoney = (v?: number | null) => (v == null ? '—' : `$${(v / 1e6).toFixed(2)}M`)

function BrokerRow({ b, side }: { b: BrokerItem; side: 'buy' | 'sell' }) {
  const isBuy = side === 'buy'
  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 px-3 py-1 text-[10px] font-mono hover:bg-secondary/20">
      <span className="truncate text-muted-foreground" title={b.broker_name}>
        {b.broker_name ?? '—'}
      </span>
      <span className={cn('tabular-nums', isBuy ? 'text-emerald-500' : 'text-red-500')}>
        {b.avg_price == null ? '—' : b.avg_price.toFixed(2)}
      </span>
      <span className={cn('text-right tabular-nums', isBuy ? 'text-emerald-400' : 'text-red-400')}>
        {fmtVol(b.net_vol)}
      </span>
      <span className="text-right text-muted-foreground/70 tabular-nums">{fmtMoney(b.total_turnover)}</span>
    </div>
  )
}

export function BrokerPanel({ symbol }: { symbol: string }) {
  const api = apiClient
  const [data, setData] = useState<TopBrokersResp | null>(null)
  const [stale, setStale] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setStale(false)
    setData(null)

    const load = async () => {
      try {
        const res = await api.get<{ data: TopBrokersResp; status: number }>(
          `/market/top-brokers/${encodeURIComponent(symbol)}`,
        )
        const body = res?.data
        if (cancelled) return
        if (body?.status === 'success' && (body.buy_brokers?.length || body.sell_brokers?.length)) {
          setData(body)
          setStale(false)
        } else {
          setStale(true)
          setData(body)
        }
      } catch {
        if (!cancelled) setStale(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    // 经纪版面非高频，30s 轮询
    const t = setInterval(load, 30000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [symbol, api])

  return (
    <div className={cn('glass-card rounded-lg overflow-hidden', stale && 'opacity-60 saturate-50')}>
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/20">
        <span className="text-[10px] font-semibold text-foreground/80">十大买卖经纪商</span>
        {stale ? (
          <span className="text-[9px] text-amber-500 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> STALE
          </span>
        ) : (
          <span className="text-[9px] text-muted-foreground">
            {data?.is_real_time ? '实时' : 'Futu'}
          </span>
        )}
      </div>

      {loading && !data ? (
        <div className="px-3 py-4 text-center text-[10px] text-muted-foreground">加载经纪商数据…</div>
      ) : status === 'unsupported' ? (
        <div className="px-3 py-4 text-center text-[10px] text-gray-400">
          {data?.message || '当前市场不支持经纪商版面'}
          <span className="ml-1 text-gray-600">(Futu 仅港股提供)</span>
        </div>
      ) : stale && !data?.buy_brokers?.length && !data?.sell_brokers?.length ? (
        <div className="px-3 py-4 text-center text-[10px] text-amber-500">
          数据源暂不可用 · 经纪商未返回
        </div>
      ) : (
        <div className="py-1">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 px-3 py-0.5 text-[9px] text-muted-foreground/60 border-b border-border/10">
            <span>经纪商</span>
            <span className="text-right">均价</span>
            <span className="text-right">净量</span>
            <span className="text-right">成交额</span>
          </div>
          <div className="text-[9px] text-emerald-500/80 px-3 pt-1">买盘经纪商</div>
          {(data?.buy_brokers?.length ? data!.buy_brokers! : []).map((b, i) => (
            <BrokerRow key={`b${i}`} b={b} side="buy" />
          ))}
          <div className="text-[9px] text-red-500/80 px-3 pt-1">卖盘经纪商</div>
          {(data?.sell_brokers?.length ? data!.sell_brokers! : []).map((b, i) => (
            <BrokerRow key={`s${i}`} b={b} side="sell" />
          ))}
        </div>
      )}
    </div>
  )
}
