import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Card, CardHeader } from './data-center-capital-flow'

interface BrokerEntry {
  name?: string
  code?: string
  net_buy?: number
  qty?: number
}

function parseBrokerQueue(data: any): { bids: BrokerEntry[]; asks: BrokerEntry[] } {
  const empty = { bids: [], asks: [] }
  if (!data) return empty
  // Futu broker_queue 可能直接是对象，或嵌套在 .broker_queue
  const raw = data.broker_queue ?? data
  if (typeof raw === 'string') {
    // 逗号分隔的经纪商名（mock 格式）
    const names = raw.split(',').map((s: string) => s.trim()).filter(Boolean)
    return { bids: names.map((n: string) => ({ name: n })), asks: [] }
  }
  try {
    const bids = Array.isArray(raw.bid_brokers) ? raw.bid_brokers : (Array.isArray(raw.bids) ? raw.bids : [])
    const asks = Array.isArray(raw.ask_brokers) ? raw.ask_brokers : (Array.isArray(raw.asks) ? raw.asks : [])
    return { bids, asks }
  } catch {
    return empty
  }
}

function BrokerList({ title, rows, accent }: { title: string; rows: BrokerEntry[]; accent: string }) {
  if (!rows || rows.length === 0) {
    return (
      <Card>
        <CardHeader title={title} />
        <div className="flex flex-col items-center justify-center gap-1 p-4 text-center">
          <p className="text-[11px] text-muted-foreground">{title}暂无经纪商</p>
        </div>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader title={title} sub={`${rows.length} 家`} />
      <div className="flex flex-col divide-y divide-border/30">
        {rows.slice(0, 10).map((b, i) => (
          <div key={b.code || b.name || i} className="flex items-center justify-between px-3 py-1.5">
            <span className="text-[11px] text-foreground truncate">{b.name || b.code}</span>
            <span className={cn('text-[11px] font-medium', accent)}>
              {b.net_buy != null ? (b.net_buy >= 0 ? `+${(b.net_buy / 1e4).toFixed(0)}万` : `${(b.net_buy / 1e4).toFixed(0)}万`) : ''}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function BrokerQueuePanel({ data, status, symbol }: { data?: any; status?: string; symbol?: string }) {
  const { bids, asks } = parseBrokerQueue(data)
  const hasData = bids.length > 0 || asks.length > 0
  return (
    <section>
      <div className="flex items-center gap-2 px-1">
        <span className="text-sm font-semibold text-foreground">港股经纪商席位队列</span>
        {symbol && <span className="text-[10px] text-muted-foreground">{symbol}</span>}
      </div>
      {hasData ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-2.5">
          <BrokerList title="买入经纪商（席位异动）" rows={bids} accent="text-emerald-400" />
          <BrokerList title="卖出经纪商" rows={asks} accent="text-rose-400" />
        </div>
      ) : (
        <Card className="mt-2.5">
          <div className="flex flex-col items-center justify-center gap-1 p-8 text-center">
            <AlertTriangle className="h-5 w-5 text-muted-foreground/40" />
            <p className="text-[11px] text-muted-foreground">经纪商席位数据未接入</p>
            <p className="text-[10px] text-muted-foreground/60">
              依赖 Futu 实时推送（需 HK 行情订阅），接入后展示买卖经纪商队列与席位异动。
            </p>
          </div>
        </Card>
      )}
    </section>
  )
}
