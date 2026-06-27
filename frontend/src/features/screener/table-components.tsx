import React, { useState, useEffect, useRef } from 'react'
import { ChevronUp, ChevronDown, ArrowUpDown, Filter, Info, Building2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { formatDisplaySymbol, getZhLabel, type SortKey } from './shared'

// ── 独立提取单行组件 (局部状态隔离，实现零GC实时跳动) ──────────────────────────────────
export const ScreenerRow = React.memo(({ r, isSelected, dynamicCols, toggleOne, handleAddAndOpen, handleAddSingle, onPreview, onSendToCopilot, onSendToBacktest }: any) => {
  const [localPrice, setLocalPrice] = useState(r.price)
  const [localChg, setLocalChg] = useState(r.chg)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const flashTimerRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    const handleQuote = (e: Event) => {
      if (document.hidden) return;
      const q = (e as CustomEvent).detail
      const ticker = q.ticker || q.requested_ticker
      if (ticker === r.symbol || ticker === r.symbol.replace(/^(US|HK|SH|SZ)\./, '')) {
        const newPrice = parseFloat(q.last_price) || 0
        const newChange = parseFloat(q.change_pct) || 0
        
        setLocalPrice((prev: number) => {
          if (newPrice !== prev && newPrice > 0) {
            if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
            setFlash(newPrice > prev ? 'up' : 'down')
            flashTimerRef.current = setTimeout(() => setFlash(null), 800)
          }
          return newPrice > 0 ? newPrice : prev
        })
        if (!isNaN(newChange)) {
          setLocalChg(newChange)
        }
      }
    }
    window.addEventListener('screener_quote_update', handleQuote)
    return () => {
      window.removeEventListener('screener_quote_update', handleQuote)
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [r.symbol])

  return (
    <tr
      className={cn(
        'hover:bg-muted/50 transition-colors group select-none cursor-pointer',
        isSelected && 'bg-primary/5 hover:bg-primary/10'
      )}
      onDoubleClick={() => onSendToCopilot(r.symbol)}
    >
      <td className="px-3 py-2.5 pl-4">
        <input
          type="checkbox"
          className="rounded-sm border-border accent-primary focus:ring-primary/30"
          checked={isSelected}
          onChange={(e) => toggleOne(r.symbol, e.target.checked)}
          aria-label={`选择 ${r.symbol}`}
        />
      </td>
      <td className="px-3 py-2.5 font-mono text-muted-foreground tabular-nums">{r.rank}</td>
      <td className="px-3 py-2.5 font-mono font-bold tabular-nums relative group/profile">
        <div className="flex items-center gap-1.5">
          <button 
            className="hover:text-primary hover:underline underline-offset-2 transition-colors relative z-10 text-left focus:outline-none"
            onClick={(e) => { e.stopPropagation(); onPreview({ symbol: r.symbol, price: localPrice !== undefined ? localPrice : r.price, change: localChg !== undefined ? localChg : r.chg }) }}
            title="点击预览 K 线图"
          >
            {formatDisplaySymbol(r.symbol)}
          </button>
          <Info className="h-3 w-3 text-muted-foreground/30 hover:text-primary transition-colors cursor-help peer shrink-0" />
          {/* 💡 公司简介悬浮卡片 (Company Profile Hover Card) */}
          <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2 w-56 bg-popover/95 backdrop-blur-md text-popover-foreground border border-border/50 shadow-2xl rounded-lg p-3 opacity-0 invisible peer-hover:opacity-100 peer-hover:visible transition-all duration-200 z-[60] flex flex-col gap-2 pointer-events-none">
            <div className="flex items-center gap-2 border-b border-border/30 pb-2">
              <Building2 className="h-4 w-4 text-indigo-500 dark:text-indigo-400 shrink-0" />
              <span className="font-bold text-xs truncate" title={r.name}>{r.name}</span>
            </div>
            <div className="flex flex-col gap-1.5 text-[10px]">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground shrink-0">证券代码</span>
                <span className="font-mono bg-secondary/50 px-1 rounded text-foreground">{r.symbol}</span>
              </div>
              {r.industry && (
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground shrink-0">所属行业</span>
                  <span className="truncate max-w-[130px] text-right font-medium text-foreground" title={r.industry}>{r.industry}</span>
                </div>
              )}
              {r.stock_plate && (
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground shrink-0">概念板块</span>
                  <span className="truncate max-w-[130px] text-right font-medium text-indigo-600 dark:text-indigo-400" title={r.stock_plate}>{r.stock_plate}</span>
                </div>
              )}
              <div className="flex justify-between items-center mt-1 pt-1.5 border-t border-border/20">
                <span className="text-muted-foreground shrink-0">市值/估值</span>
                <span className="font-mono font-bold text-foreground flex gap-1.5">
                  {r.market_cap ? (r.market_cap >= 1e12 ? (r.market_cap/1e12).toFixed(2)+'万亿' : r.market_cap >= 1e8 ? (r.market_cap/1e8).toFixed(2)+'亿' : r.market_cap.toLocaleString()) : '--'}
                  {r.pe_ttm ? <span className="opacity-80 text-muted-foreground">| PE: {r.pe_ttm.toFixed(1)}</span> : ''}
                </span>
              </div>
            </div>
          </div>
        </div>
      </td>
      <td className="px-3 py-2.5 font-medium whitespace-nowrap text-foreground/90">{r.name}</td>
      {dynamicCols.map((col: string) => {
        let val = r[col];
        if (col === 'price' && localPrice !== undefined) val = localPrice;
        if (col === 'chg' && localChg !== undefined) val = localChg;
        
        let displayVal: any = val;
        let colorClass = "text-foreground/80";

        let isNum = typeof val === 'number';
        let numVal = val;
        if (!isNum && typeof val === 'string' && val.trim() !== '') {
          if (!val.includes('%') && !isNaN(Number(val))) {
            isNum = true;
            numVal = Number(val);
          }
        }

        if (isNum) {
          displayVal = numVal.toLocaleString('en-US', { maximumFractionDigits: 3 });
          const isPureRatio = ['current_ratio', 'property_ratio', 'quick_ratio', 'equity_multiplier', 'asset_turnover', 'inventory_turnover'].some(k => col.includes(k));
          const isPct = !isPureRatio && ['change', 'chg', 'growth', 'rate', 'ratio', 'yield', 'roe', 'roa', 'margin', 'pct', 'cover', 'percentile'].some(k => col.includes(k));
          const isSmallMetric = ['price', 'pe', 'pb', 'eps', 'ps', 'pcf', 'score', 'rank'].some(k => col.includes(k) && !col.includes('price_to'));

          if (isPureRatio) {
            displayVal = numVal.toFixed(2);
            colorClass = "text-foreground font-medium";
          } else if (isPct) {
            const pctVal = numVal * 100;
            displayVal = pctVal.toLocaleString('en-US', { maximumFractionDigits: 2 });
            if (pctVal > 0) { displayVal = '+' + displayVal + '%'; colorClass = 'text-emerald-600 dark:text-emerald-400 font-semibold'; } 
            else if (pctVal < 0) { displayVal = displayVal + '%'; colorClass = 'text-red-600 dark:text-red-400 font-semibold'; } 
            else { displayVal = '0.00%'; colorClass = 'text-muted-foreground'; }
          } else if (!isSmallMetric && Math.abs(numVal) >= 10000) {
             const absVal = Math.abs(numVal);
             if (absVal >= 1e12) displayVal = (numVal / 1e12).toFixed(2) + '万亿';
             else if (absVal >= 1e8) displayVal = (numVal / 1e8).toFixed(2) + '亿';
             else if (absVal >= 1e4) displayVal = (numVal / 1e4).toFixed(2) + '万';
             colorClass = "text-foreground font-medium";
          } else {
             colorClass = "text-foreground font-medium";
          }
        } else if (val === undefined || val === null) {
          displayVal = '--'; colorClass = "text-muted-foreground";
        } else if (typeof val === 'string') {
          if (val.startsWith('+') && !val.includes('万') && !val.includes('亿')) colorClass = 'text-emerald-600 dark:text-emerald-400 font-semibold';
          else if (val.startsWith('-') && !val.includes('万') && !val.includes('亿') && val !== '-') colorClass = 'text-red-600 dark:text-red-400 font-semibold';
          else if (val === '-') { displayVal = '--'; colorClass = "text-muted-foreground"; }
          
          if (col === 'matched_patterns') {
             displayVal = val.split(', ').map((p: string, i: number) => (
               <span key={i} className="inline-block bg-violet-500/10 text-violet-600 dark:text-violet-400 px-1.5 py-0.5 rounded border border-violet-500/20 mr-1 mt-0.5 last:mr-0 text-[10px] whitespace-nowrap">{p}</span>
             ));
          }
        }

        let cellBg = '';
        if (flash === 'up' && (col === 'price' || col === 'chg')) cellBg = 'bg-emerald-500/15 transition-none';
        else if (flash === 'down' && (col === 'price' || col === 'chg')) cellBg = 'bg-red-500/15 transition-none';
        else cellBg = 'transition-colors duration-500';

        return <td key={col} className={cn("px-3 py-2.5 text-right font-mono tabular-nums whitespace-nowrap", colorClass, cellBg)}>{displayVal}</td>
      })}
      
      <td className="px-3 py-2.5 pr-4">
        <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button className="text-[10px] px-2 py-1 rounded border border-primary/30 text-primary hover:bg-primary hover:text-primary-foreground transition-colors font-medium whitespace-nowrap" title={`推入自选池: ${r.symbol}`} onClick={(e) => { e.stopPropagation(); handleAddSingle(r.symbol) }}>+ 自选</button>
          <button className="text-[10px] px-2 py-1 rounded border border-violet-500/30 text-violet-600 dark:text-violet-400 hover:bg-violet-500 hover:text-white transition-colors font-medium whitespace-nowrap" title={`AI深度分析: ${r.symbol}`} onClick={(e) => { e.stopPropagation(); onSendToCopilot(r.symbol); }}>AI 分析</button>
        <button className="text-[10px] px-2 py-1 rounded border border-indigo-500/30 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500 hover:text-white transition-colors font-medium whitespace-nowrap" title={`回测验证: ${r.symbol}`} onClick={(e) => { e.stopPropagation(); onSendToBacktest(r.symbol); }}>回测</button>
        </div>
      </td>
    </tr>
  )
}, (prev, next) => {
  return prev.r === next.r && prev.isSelected === next.isSelected && prev.dynamicCols === next.dynamicCols;
})

export function SortableTh({ label, k, sortKey, sortDir, onSort, align = 'right', className, filterRange, onApplyFilter, onClearFilter }: {
  label: string; k: SortKey; sortKey: SortKey; sortDir: 1 | -1; onSort: (k: SortKey) => void; align?: 'left' | 'right' | 'center'; className?: string; filterRange?: { min: string; max: string }; onApplyFilter?: (range: { min: string; max: string }) => void; onClearFilter?: () => void
}) {
  const active = sortKey === k
  const [showFilter, setShowFilter] = useState(false)
  const [minVal, setMinVal] = useState(filterRange?.min || '')
  const [maxVal, setMaxVal] = useState(filterRange?.max || '')
  const filterRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMinVal(filterRange?.min || '')
    setMaxVal(filterRange?.max || '')
  }, [filterRange])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setShowFilter(false)
      }
    }
    if (showFilter) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showFilter])

  const handleApply = (e: React.MouseEvent) => {
    e.stopPropagation()
    onApplyFilter?.({ min: minVal, max: maxVal })
    setShowFilter(false)
  }

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation()
    setMinVal('')
    setMaxVal('')
    onClearFilter?.()
    setShowFilter(false)
  }

  const isFiltered = !!(filterRange?.min || filterRange?.max)

  return (
    <th scope="col" className={cn("px-3 py-2 whitespace-nowrap group/th hover:bg-secondary/50 transition-colors relative", 
      align === 'left' ? 'text-left' : align === 'center' ? 'text-center' : 'text-right', className || 'min-w-[100px]'
    )}>
      <div className={cn("flex items-center gap-1", align === 'left' ? 'justify-start' : align === 'center' ? 'justify-center' : 'justify-end')}>
        <button onClick={() => onSort(k)} className={cn('flex items-center gap-0.5 text-xs font-medium transition-colors outline-none cursor-pointer', active ? 'text-primary' : 'text-muted-foreground group-hover/th:text-foreground')} title={`按 ${label} 排序`} tabIndex={-1}>
          {label}
          {active ? sortDir === -1 ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" /> : <ArrowUpDown className="h-3 w-3 opacity-0 group-hover/th:opacity-50 transition-opacity" />}
        </button>
        {onApplyFilter && (
          <div ref={filterRef} className="relative flex items-center">
            <button onClick={(e) => { e.stopPropagation(); setShowFilter(!showFilter); }} className={cn("p-1 rounded transition-colors", isFiltered ? "text-amber-500 bg-amber-500/10" : "text-muted-foreground opacity-0 group-hover/th:opacity-100 hover:bg-secondary/80")} title="过滤区间">
              <Filter className="h-3 w-3" />
            </button>
            {showFilter && (
              <div className="absolute top-full right-0 mt-1.5 w-48 bg-card text-card-foreground border border-border/50 rounded-lg shadow-xl p-3 z-50 flex flex-col gap-3 cursor-default" onClick={(e) => e.stopPropagation()}>
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider text-left">设置过滤区间</span>
                <div className="flex items-center gap-2">
                  <input type="number" placeholder="Min" value={minVal} onChange={(e) => setMinVal(e.target.value)} className="w-full bg-secondary/50 border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary transition-colors tabular-nums" />
                  <span className="text-muted-foreground">-</span>
                  <input type="number" placeholder="Max" value={maxVal} onChange={(e) => setMaxVal(e.target.value)} className="w-full bg-secondary/50 border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary transition-colors tabular-nums" />
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <Button size="sm" variant="outline" className="h-6 text-[10px] flex-1" onClick={handleClear}>清除</Button>
                  <Button size="sm" className="h-6 text-[10px] flex-1" onClick={handleApply}>应用</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </th>
  )
}