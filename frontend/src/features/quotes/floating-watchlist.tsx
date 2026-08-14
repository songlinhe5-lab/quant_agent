'use client'

import React, { useState, useRef, useEffect } from 'react'
import { List, X, Search, GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { WatchlistItem } from '@/stores/use-watchlist'
import { SymbolContextMenu } from '@/components/symbol-context-menu'

const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')

function fmtSymbol(sym: string) {
  if (sym.startsWith('US.')) return sym.replace('US.', '')
  if (sym.startsWith('HK.')) return `${sym.replace('HK.', '')}.HK`
  if (sym.startsWith('SH.')) return `${sym.replace('SH.', '')}.SH`
  if (sym.startsWith('SZ.')) return `${sym.replace('SZ.', '')}.SZ`
  return sym
}

/**
 * PROD-04a: 盯盘模式下自选列表改为可拖拽悬浮球样式。
 * 悬浮球可拖动，点击展开自选浮层；浮层内标的支持选中与移除。
 */
export function FloatingWatchlist({ watchlist, selectedSymbol, setSelectedSymbol, addTicker, removeTicker }: {
  watchlist: WatchlistItem[]
  selectedSymbol: string
  setSelectedSymbol: (sym: string) => void
  addTicker: (sym: string) => void
  removeTicker: (sym: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [pos, setPos] = useState({ x: 16, y: 96 })
  const [live, setLive] = useState<Record<string, { price: number; change: number }>>({})
  const drag = useRef<{ startX: number; startY: number; origX: number; origY: number; moved: boolean } | null>(null)
  const ballRef = useRef<HTMLDivElement>(null)

  // 实时价格/涨跌幅跟随
  useEffect(() => {
    const handler = (e: Event) => {
      const q = (e as CustomEvent).detail
      const ticker = q.ticker || q.requested_ticker
      if (!ticker) return
      const sym = cleanSym(String(ticker))
      const price = parseFloat(q.last_price) || 0
      const change = parseFloat(String(q.change_pct ?? '0').replace('%', '')) || 0
      setLive(prev => ({ ...prev, [sym]: { price, change } }))
    }
    window.addEventListener('quote_update', handler)
    return () => window.removeEventListener('quote_update', handler)
  }, [])

  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y, moved: false }
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const dx = e.clientX - drag.current.startX
    const dy = e.clientY - drag.current.startY
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) drag.current.moved = true
    const maxX = window.innerWidth - 64
    const maxY = window.innerHeight - 64
    setPos({ x: Math.max(8, Math.min(maxX, drag.current.origX + dx)), y: Math.max(80, Math.min(maxY, drag.current.origY + dy)) })
  }
  const onPointerUp = () => {
    const moved = drag.current?.moved
    drag.current = null
    if (!moved) setOpen(o => !o)
  }

  const filtered = query ? watchlist.filter(w => w.symbol.toLowerCase().includes(query.toLowerCase())) : watchlist

  return (
    <>
      {/* 悬浮球 */}
      <div
        ref={ballRef}
        className="fixed z-40 flex flex-col items-center gap-1 select-none"
        style={{ left: pos.x, top: pos.y }}
      >
        <button
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className="group relative w-12 h-12 rounded-full bg-card/90 backdrop-blur-md border border-[hsl(var(--scene-accent))]/60 shadow-[0_0_18px_rgba(0,0,0,0.45)] hover:shadow-[0_0_22px_hsl(var(--scene-accent)/0.5)] transition-shadow cursor-grab active:cursor-grabbing flex items-center justify-center"
          title="拖拽移动 · 点击展开自选池"
          aria-label="自选池悬浮球"
        >
          <List className="w-5 h-5 text-[hsl(var(--scene-accent))]" />
          {watchlist.length > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[hsl(var(--scene-accent))] text-[9px] font-bold text-background flex items-center justify-center">
              {watchlist.length}
            </span>
          )}
        </button>
      </div>

      {/* 自选浮层 */}
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="fixed z-50 w-64 max-h-[60vh] flex flex-col rounded-xl border border-border/50 bg-card/95 backdrop-blur-xl shadow-2xl overflow-hidden"
            style={{ left: Math.min(pos.x, window.innerWidth - 268), top: Math.min(pos.y + 52, window.innerHeight - 360) }}
          >
            <div className="px-3 py-2 border-b border-border/40 bg-secondary/30 flex items-center justify-between">
              <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-1.5">
                <GripVertical className="w-3.5 h-3.5 text-[hsl(var(--scene-accent))]" /> 自选池
              </span>
              <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground" aria-label="关闭"><X className="w-3.5 h-3.5" /></button>
            </div>
            <div className="px-2 py-2 border-b border-border/20 bg-background/40">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <input
                  type="text" placeholder="搜索或添加标的..." value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && query) { addTicker(query.toUpperCase()); setQuery('') } }}
                  className="w-full h-7 bg-secondary/30 border border-border/50 rounded-md pl-7 pr-2 text-[11px] font-mono focus:outline-none focus:border-[hsl(var(--scene-accent))]/50 transition-colors"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {filtered.length === 0 ? (
                <div className="px-3 py-6 text-center text-[10px] text-muted-foreground font-mono">自选为空</div>
              ) : (
                filtered.map(item => {
                  const sym = cleanSym(item.symbol)
                  const l = live[sym]
                  const price = l?.price || item.price
                  const change = l?.change ?? (typeof item.change === 'number' ? item.change : 0)
                  return (
                    <SymbolContextMenu key={item.symbol} symbol={item.symbol} onRemove={removeTicker} onSelect={() => setSelectedSymbol(item.symbol)}>
                      <div
                        onClick={() => setSelectedSymbol(item.symbol)}
                        className={cn(
                          'flex items-center justify-between gap-2 px-3 py-2 border-b border-border/20 cursor-pointer transition-colors',
                          selectedSymbol === item.symbol ? 'bg-[hsl(var(--scene-accent)/0.12)]' : 'hover:bg-secondary/50'
                        )}
                      >
                        <span className="text-[11px] font-bold font-mono truncate">{fmtSymbol(item.symbol)}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono tabular-nums text-muted-foreground">{price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                          <span className={cn('text-[10px] font-mono font-semibold tabular-nums w-12 text-right', change >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                            {change >= 0 ? '+' : ''}{change.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    </SymbolContextMenu>
                  )
                })
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}
