import React, { useState, useRef, useEffect, useMemo } from 'react'
import { Eye, Search, X, GripVertical, ArrowUpDown, ChevronLeft } from 'lucide-react'
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ResizablePanel as Panel } from '@/components/ui/resizable'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { WatchlistItem } from '@/stores/use-watchlist'

function MiniSparkline({ dirs, theme }: { dirs: number[], theme?: string }) {
  const w = 40, h = 14
  const pts = dirs.reduce<{ x: number; y: number }[]>((acc, d, i) => {
    const prev = acc[acc.length - 1]?.y ?? h / 2
    acc.push({ x: (i / (dirs.length - 1)) * w, y: Math.max(2, Math.min(h - 2, prev - d * 2.5)) })
    return acc
  }, [])
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const lastDir = dirs[dirs.length - 1]
  
  const upColor = theme === 'dark' ? 'rgb(52,211,153)' : 'rgb(5,150,105)'
  const downColor = theme === 'dark' ? 'rgb(248,113,113)' : 'rgb(220,38,38)'
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="flex-shrink-0">
      <path d={path} fill="none" stroke={lastDir > 0 ? upColor : downColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const SortableWatchlistItem = React.memo(function SortableWatchlistItem({ item, isSelected, theme, allowDrag, onSelect, onRemove }: {
  item: WatchlistItem; isSelected: boolean; theme?: string; allowDrag: boolean; onSelect: () => void; onRemove: (sym: string) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.symbol })
  const style = { transform: CSS.Transform.toString(transform), transition, zIndex: isDragging ? 1 : 0, position: isDragging ? 'relative' as const : undefined }

  const [localPrice, setLocalPrice] = useState(item.price)
  const [localChange, setLocalChange] = useState(item.change)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const flashTimerRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    const handleQuote = (e: Event) => {
      if (document.hidden) return;
      const q = (e as CustomEvent).detail
      const ticker = q.ticker || q.requested_ticker
      
      const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
      if (cleanSym(ticker) === cleanSym(item.symbol)) {
        const newPrice = parseFloat(q.last_price) || 0
        const newChange = parseFloat(q.change_pct) || 0
        
        setLocalPrice(prev => {
          if (newPrice !== prev) {
            if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
            setFlash(newPrice > prev ? 'up' : 'down')
            flashTimerRef.current = setTimeout(() => setFlash(null), 800)
          }
          return newPrice
        })
        setLocalChange(newChange)
      }
    }
    window.addEventListener('quote_update', handleQuote)
    return () => {
      window.removeEventListener('quote_update', handleQuote)
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [item.symbol])

  return (
    <div ref={setNodeRef} style={style} className={cn(
      'flex flex-col gap-1 px-3 py-2 border-b border-border/20 last:border-b-0 transition-colors text-left focus:outline-none focus:ring-1 focus:ring-primary/50',
      isSelected ? 'bg-primary/10' : 'hover:bg-secondary/50 bg-transparent',
      isDragging ? 'bg-background shadow-xl opacity-90' : '',
      flash === 'up' && 'tick-up', flash === 'down' && 'tick-down'
    )}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1 min-w-0">
          <div {...attributes} {...(allowDrag ? listeners : {})} className={cn("p-1 -ml-1 text-muted-foreground/50 transition-colors outline-none", allowDrag ? "cursor-grab active:cursor-grabbing hover:text-foreground" : "w-0 p-0 m-0 overflow-hidden opacity-0 pointer-events-none")} title={allowDrag ? "拖拽排序" : ""}><GripVertical className="h-3.5 w-3.5" /></div>
          <span className="text-[11px] font-bold font-mono cursor-pointer truncate" onClick={onSelect}>
            {item.symbol.startsWith('US.') ? item.symbol.replace('US.', '') : item.symbol.startsWith('HK.') ? `${item.symbol.replace('HK.', '')}.HK` : item.symbol.startsWith('SH.') ? `${item.symbol.replace('SH.', '')}.SH` : item.symbol.startsWith('SZ.') ? `${item.symbol.replace('SZ.', '')}.SZ` : item.symbol}
          </span>
        </div>
        <button onClick={(e) => { e.stopPropagation(); onRemove(item.symbol) }} className="p-0.5 text-muted-foreground hover:text-red-500 dark:hover:text-red-400 hover:bg-red-500/10 dark:hover:bg-red-400/10 rounded transition-colors z-10" title="移除自选"><X className="h-3 w-3" /></button>
      </div>
      <div className="flex items-center justify-between cursor-pointer pl-6" onClick={onSelect}>
        <span className="text-[10px] font-mono tabular-nums text-muted-foreground">{localPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        <span className={cn('text-[10px] font-mono font-semibold tabular-nums', localChange >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>{localChange >= 0 ? '+' : ''}{localChange.toFixed(2)}%</span>
      </div>
      <div className="mt-1 opacity-80 pl-6 cursor-pointer" onClick={onSelect}><MiniSparkline dirs={item.sparkDir} theme={theme} /></div>
    </div>
  )
}, (prev, next) => prev.item.symbol === next.item.symbol && prev.isSelected === next.isSelected && prev.theme === next.theme && prev.allowDrag === next.allowDrag)

export const WatchlistSidebar = React.memo(function WatchlistSidebar({ watchlist, selectedSymbol, setSelectedSymbol, theme, toggleWatchlist, addTicker, removeTicker, reorderWatchlist, latestStatsRef }: { watchlist: WatchlistItem[]; selectedSymbol: string; setSelectedSymbol: (sym: string) => void; theme?: string; toggleWatchlist: () => void; addTicker: (sym: string) => void; removeTicker: (sym: string) => void; reorderWatchlist: (o: number, n: number) => void; latestStatsRef: React.MutableRefObject<Record<string, {change: number, vol: number}>> }) {
  const [sortMode, setSortMode] = useState<'manual' | 'change_desc' | 'change_asc' | 'vol_desc'>('manual')
  const [sortTick, setSortTick] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')

  const displayWatchlist = useMemo(() => {
    let list = watchlist;
    if (searchQuery) list = list.filter(w => w.symbol.toLowerCase().includes(searchQuery.toLowerCase()));
    if (sortMode === 'manual') return list;
    return [...list].sort((a, b) => {
      const cleanA = (a.symbol||'').replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, ''); const cleanB = (b.symbol||'').replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
      const statA = latestStatsRef.current[cleanA] || { change: 0, vol: 0 }; const statB = latestStatsRef.current[cleanB] || { change: 0, vol: 0 }
      if (sortMode === 'change_desc') return statB.change - statA.change; if (sortMode === 'change_asc') return statA.change - statB.change; if (sortMode === 'vol_desc') return statB.vol - statA.vol; return 0;
    });
  }, [watchlist, sortMode, sortTick, searchQuery, latestStatsRef]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }))
  const handleDragEnd = (event: DragEndEvent) => { const { active, over } = event; if (over && active.id !== over.id) { const oldIndex = watchlist.findIndex(item => item.symbol === active.id); const newIndex = watchlist.findIndex(item => item.symbol === over.id); reorderWatchlist(oldIndex, newIndex); setSortMode('manual'); } }

  return (
    <Panel defaultSize={20} minSize={15} maxSize={30} className="flex flex-col bg-background/50 glass-card rounded-xl shadow-sm border-border/40 overflow-hidden">
      <div className="px-3 py-2.5 border-b border-border/40 bg-secondary/20 flex items-center justify-between shrink-0"><span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground flex items-center gap-1.5"><Eye className="w-3.5 h-3.5" /> 自选池</span><div className="flex items-center gap-1"><button onClick={() => { setSortMode(prev => prev === 'change_desc' ? 'change_asc' : 'change_desc'); setSortTick(t => t + 1) }} className={cn("p-1 rounded transition-colors text-muted-foreground", sortMode.includes('change') ? "bg-primary/20 text-primary" : "hover:bg-secondary/80")} title="涨跌幅排序"><ArrowUpDown className="w-3.5 h-3.5" /></button><Button variant="ghost" size="icon" onClick={toggleWatchlist} className="h-6 w-6 rounded-md hover:bg-secondary/80" title="收起列表"><ChevronLeft className="w-4 h-4" /></Button></div></div>
      <div className="px-2 py-2 border-b border-border/20 bg-background/50 shrink-0"><div className="relative"><Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" /><input type="text" placeholder="搜索或添加标的..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && searchQuery) { addTicker(searchQuery.toUpperCase()); setSearchQuery('') } }} className="w-full h-7 bg-secondary/30 border border-border/50 rounded-md pl-7 pr-2 text-[11px] font-mono focus:outline-none focus:border-primary/50 transition-colors" /></div></div>
      <div className="flex-1 overflow-y-auto custom-scrollbar relative">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}><SortableContext items={displayWatchlist.map(w => w.symbol)} strategy={verticalListSortingStrategy}>{displayWatchlist.map(item => <SortableWatchlistItem key={item.symbol} item={item} isSelected={selectedSymbol === item.symbol} theme={theme} allowDrag={sortMode === 'manual' && !searchQuery} onSelect={() => setSelectedSymbol(item.symbol)} onRemove={removeTicker} />)}</SortableContext></DndContext>
      </div>
    </Panel>
  )
})