'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { toMarketSymbol } from './symbol-utils'
import { apiClient } from '@/lib/api-client'
import { Activity } from 'lucide-react'

interface DepthRow {
  price: number
  size: number
  total: number
}

interface TapeTick {
  price: number
  volume: number
  side: 'B' | 'S' | 'N'
  time: string
}

const DEPTH_LEVELS = [5, 10, 20, 40]

/** 防御式读取盘口档位（后端返回 {price, size}） */
function toRows(raw: any[]): DepthRow[] {
  if (!Array.isArray(raw)) return []
  let cum = 0
  return raw
    .filter((r) => r && typeof r.price === 'number' && typeof r.size === 'number')
    .map((r) => {
      cum += r.size
      return { price: r.price, size: r.size, total: cum }
    })
}

/**
 * 个股工作台 · 右栏 [盘口] tab 的 PixUi 档价盘口（设计稿 Frame 4 盘口视图）。
 * - 买卖五档（深度条 + 价格色），档位数可在 5/10/20/40 切换
 * - 成交笔数（逐笔成交 tape）
 * - 主力栏（9 档主力筹码 in/out，来自 /market/capital-distribution）
 * 数据优先走 /market/order-book（Futu OpenD），缺失时本地合成演示档位以避免白屏。
 */
export function OrderBookDepthPanel({ symbol }: { symbol: string }) {
  const futu = toMarketSymbol(symbol)
  const [depth, setDepth] = useState<number>(5)
  const [asks, setAsks] = useState<DepthRow[]>([])
  const [bids, setBids] = useState<DepthRow[]>([])
  const [tape, setTape] = useState<TapeTick[]>([])
  const [mainLayers, setMainLayers] = useState<{ name: string; in: number; out: number }[] | null>(null)
  const [mainStale, setMainStale] = useState(false)
  const [stale, setStale] = useState(false)
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled = false
    const sym = encodeURIComponent(futu)
    setStale(false)
    setMainStale(false)

    // 档位盘口（后端返回 {price, size}）
    apiClient
      .get<{ data: { asks?: any[]; bids?: any[]; last_price?: number } }>(
        `/market/order-book?ticker=${sym}`,
      )
      .then((r) => {
        if (cancelled) return
        const d = r.data
        if (d?.asks?.length && d?.bids?.length) {
          setAsks(toRows(d.asks))
          setBids(toRows(d.bids))
          if (d.last_price != null) setLastPrice(d.last_price)
          setStale(false)
        } else {
          setStale(true)
        }
      })
      .catch(() => !cancelled && setStale(true))

    // 主力资金分层（path 参数接口）
    apiClient
      .get<{ data: any }>(`/market/capital-distribution/${sym}`)
      .then((r) => {
        if (cancelled) return
        const d = r.data
        if (!d) {
          setMainStale(true)
          return
        }
        const layers = Array.isArray(d.layers)
          ? d.layers
          : Array.isArray(d.data?.layers)
            ? d.data.layers
            : null
        if (layers) {
          setMainLayers(
            layers.map((l: any) => ({
              name: String(l.name ?? l.label ?? l.capital_class ?? 'L'),
              in: Number(l.in ?? l.in_amount ?? l.capital_in ?? 0),
              out: Number(l.out ?? l.out_amount ?? l.capital_out ?? 0),
            })),
          )
        }
      })
      .catch(() => !cancelled && setMainStale(true))

    // 实时逐笔（轻量 WS）
    try {
      const base = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'
      const ws = new WebSocket(`${base}/ws/tape?ticker=${sym}`)
      ws.onmessage = (e) => {
        if (cancelled) return
        try {
          const t = JSON.parse(e.data) as TapeTick
          setTape((prev) => [t, ...prev].slice(0, 40))
          if (t.price) setLastPrice(t.price)
        } catch {
          /* ignore */
        }
      }
      wsRef.current = ws
    } catch {
      /* WS 不可用时仅用 REST */
    }

    return () => {
      cancelled = true
      wsRef.current?.close()
    }
  }, [futu])

  const maxTotal = Math.max(
    1,
    ...asks.slice(0, depth).map((a) => a.total),
    ...bids.slice(0, depth).map((b) => b.total),
  )
  const spread =
    asks[0]?.price != null && bids[0]?.price != null ? asks[0].price - bids[0].price : 0
  const spreadPct = lastPrice && spread ? (spread / lastPrice) * 100 : 0

  const renderRows = (rows: DepthRow[], side: 'ask' | 'bid') =>
    rows
      .slice(0, depth)
      .map((r, i) => (
        <div key={`${side}-${i}`} className="relative grid grid-cols-3 text-[11px] font-mono py-0.5 px-1 rounded-sm">
          <div
            className={cn('absolute inset-0', side === 'ask' ? 'bg-red-400/10' : 'bg-emerald-400/10')}
            style={{
              width: `${(r.total / maxTotal) * 100}%`,
              marginLeft: side === 'ask' ? 'auto' : 0,
            }}
          />
          <span className={cn('relative', side === 'ask' ? 'text-red-400' : 'text-emerald-400')}>
            {r.price.toFixed(2)}
          </span>
          <span className="relative text-right text-foreground/80">{r.size}</span>
          <span className="relative text-right text-muted-foreground">{r.total}</span>
        </div>
      ))

  return (
    <div className="flex flex-col gap-2 overflow-y-auto custom-scrollbar">
      {/* 档位数切换 */}
      <div className="flex items-center gap-1.5 px-1">
        <span className="text-[9px] text-muted-foreground/70">档位</span>
        {DEPTH_LEVELS.map((lv) => (
          <button
            key={lv}
            onClick={() => setDepth(lv)}
            className={cn(
              'px-2 py-0.5 rounded text-[10px] font-mono transition-colors',
              depth === lv ? 'bg-primary/20 text-primary' : 'text-slate-400 hover:text-slate-200 border border-border/40',
            )}
          >
            {lv}
          </button>
        ))}
        {stale && (
          <span className="ml-auto text-amber-500 text-[9px] flex items-center gap-1">
            <Activity className="h-3 w-3" /> STALE
          </span>
        )}
      </div>

      {/* 买卖档（PixUi 风格深度条） */}
      <div className="glass-card rounded-lg overflow-hidden px-2 py-1.5">
        <div className="grid grid-cols-3 text-[9px] text-muted-foreground px-1 mb-1">
          <span>价格</span>
          <span className="text-right">量</span>
          <span className="text-right">累计</span>
        </div>
        <div className="space-y-0.5">{renderRows([...asks].reverse(), 'ask')}</div>
        <div className="flex items-center justify-center gap-2 py-1 border-y border-border/40 my-1">
          <span className="text-[10px] text-muted-foreground">价差</span>
          <span className="font-mono text-[11px]">{spread.toFixed(2)}</span>
          <span className="text-[9px] text-muted-foreground">({spreadPct.toFixed(3)}%)</span>
        </div>
        <div className="space-y-0.5">{renderRows(bids, 'bid')}</div>
      </div>

      {/* 成交笔数（逐笔 tape） */}
      <div className={cn('glass-card rounded-lg overflow-hidden', stale && 'opacity-60 saturate-50')}>
        <div className="px-3 py-1.5 border-b border-border/30 flex items-center gap-2">
          <Activity className="h-3 w-3 text-muted-foreground" />
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">成交笔数</span>
          <span className="ml-auto text-[9px] text-slate-500 font-mono">{tape.length} 笔</span>
        </div>
        <div className="max-h-32 overflow-y-auto custom-scrollbar divide-y divide-border/20">
          {tape.length === 0 ? (
            <div className="px-3 py-2 text-[10px] text-amber-500/90 flex items-center gap-1.5">
              <Activity className="h-3 w-3" />
              {stale ? '数据源暂不可用 · 逐笔成交未推送' : '暂无逐笔成交'}
            </div>
          ) : (
            tape.map((t, i) => (
              <div key={i} className="grid grid-cols-3 text-[10px] font-mono px-3 py-0.5">
                <span className={t.side === 'B' ? 'text-emerald-400' : t.side === 'S' ? 'text-red-400' : 'text-slate-300'}>
                  {t.price.toFixed(2)}
                </span>
                <span className="text-right text-foreground/80">{t.volume}</span>
                <span className="text-right text-muted-foreground">{t.time}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 主力栏（9 档主力筹码 in/out） */}
      <div className={cn('glass-card rounded-lg overflow-hidden', mainStale && 'opacity-60 saturate-50')}>
        <div className="px-3 py-1.5 border-b border-border/30 flex items-center gap-2">
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">主力栏</span>
          <span className="ml-auto text-[9px] text-slate-500">买 / 卖按档</span>
        </div>
        <div className="p-2">
          {mainLayers && mainLayers.length > 0 ? (
            <div className="flex items-end gap-1 h-24">
              {mainLayers.map((l) => {
                const max = Math.max(1, ...mainLayers.map((x) => Math.max(x.in, x.out)))
                return (
                  <div key={l.name} className="flex-1 flex flex-col items-center justify-end gap-0.5 h-full">
                    <div className="w-full flex flex-col justify-end h-full gap-0.5">
                      <div className="w-full bg-emerald-400/40 rounded-sm" style={{ height: `${(l.in / max) * 100}%` }} />
                      <div className="w-full bg-red-400/40 rounded-sm" style={{ height: `${(l.out / max) * 100}%` }} />
                    </div>
                    <span className="text-[8px] text-muted-foreground truncate max-w-full">{l.name}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-[10px] text-amber-500/90 text-center py-6">
              {mainStale ? '数据源暂不可用 · 主力分层未返回' : '暂无主力分层数据'}
            </div>
          )}
        </div>
        <div className="px-3 py-1.5 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
          数据源：Facade Futu · PixUi v8 · PriceLine Bid/Ask 四价
          {mainStale && <span className="ml-1 text-amber-500">· STALE</span>}
        </div>
      </div>
    </div>
  )
}
