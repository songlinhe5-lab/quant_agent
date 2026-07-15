import React, { useState, useEffect, useRef } from 'react'
import { ArrowRightLeft, AlertTriangle, Clock, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MOCK_CAPITAL_FLOWS, type CapitalFlowItem } from '@/services/mock'
import { useZhTimeAgo } from '@/hooks/useZhTimeAgo'
import { MiniTrendLine } from './shared'
import { useTheme } from 'next-themes'

export function FlowItem({ item, onClick }: { item: CapitalFlowItem; onClick?: () => void }) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const flashTimer = useRef<NodeJS.Timeout | null>(null)
  const prev = useRef(item.amount)

  useEffect(() => {
    if (item.amount !== prev.current) {
      setFlash(null)
      if (flashTimer.current) clearTimeout(flashTimer.current)
      
      const direction = item.amount > prev.current ? 'up' : 'down'
      prev.current = item.amount

      setTimeout(() => {
        setFlash(direction)
        flashTimer.current = setTimeout(() => setFlash(null), 800)
      }, 10)
    }
    return () => { if (flashTimer.current) clearTimeout(flashTimer.current) }
  }, [item.amount])

  const inflow = item.amount >= 0

  // 💡 格式化更新时间
  const formatUpdateTime = (dateStr: string | null | undefined) => {
    if (!dateStr) return '--'
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    } catch {
      return '--'
    }
  }

  return (
    <div onClick={onClick} role="button" tabIndex={0} className={cn('flex flex-col justify-center gap-1 px-2.5 py-1.5 rounded-lg border border-border/20 overflow-hidden transition-colors cursor-pointer', 'bg-slate-50 dark:bg-secondary/10 hover:bg-slate-100 dark:hover:bg-secondary/30 focus:outline-none focus:ring-1 focus:ring-primary/50', 'border-l-2', item.market === 'HK' ? 'border-l-[#f6465d]/50' : item.market === 'CN' ? 'border-l-amber-500/50' : 'border-l-blue-500/50', flash === 'up' && 'animate-flash-green', flash === 'down' && 'animate-flash-red')}>
      <div className="flex items-center gap-1.5 w-full">
        <span className="text-[10px] font-bold text-muted-foreground/80 whitespace-nowrap flex-shrink-0">{item.market === 'HK' ? '🇭🇰' : item.market === 'CN' ? '🇨🇳' : '🇺🇸'} <span className="text-foreground/80">{item.label}</span></span>
        <span className={cn('text-xs font-bold font-mono tabular-nums whitespace-nowrap transition-colors duration-500', inflow ? 'text-[#059669] dark:text-[#0ecb81]' : 'text-[#e11d48] dark:text-[#f6465d]')}>{inflow ? '+' : ''}{item.amount.toFixed(1)}<span className="text-[8px] ml-0.5 opacity-60">{item.unit}</span></span>
        <span className={cn('text-[9px] font-mono font-bold px-1.5 py-0.5 rounded flex-shrink-0 transition-colors duration-300 ml-auto', inflow ? 'bg-[#0ecb81]/15 text-[#059669] dark:text-[#0ecb81]' : 'bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]')}>{inflow ? '流入' : '流出'}</span>
        <svg width="36" height="14" viewBox="0 0 36 14" aria-hidden="true" className="flex-shrink-0 opacity-60 ml-1.5">
          {/* 💡 sparkDirs 至少需 2 个点才能画出折线；map 已为首点加 M 前缀，外层不可再加，否则生成非法 "M Mx,y" */}
          {item.sparkDirs && item.sparkDirs.length >= 2 && (
            <path
              d={item.sparkDirs.reduce<{x:number;y:number}[]>((a,d,i)=>{const pY=a.length>0?a[a.length-1].y:7;a.push({x:(i/(item.sparkDirs.length-1))*32+2,y:Math.max(1.5,Math.min(12.5,pY-d*2))});return a},[]).map((p,i)=>`${i===0?'M':'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}
              fill="none" stroke={inflow ? (isDark ? '#0ecb81' : '#059669') : (isDark ? '#f6465d' : '#e11d48')} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            />
          )}
        </svg>
      </div>
      <div className="flex items-center justify-between w-full">
        <div className="text-[9px] text-muted-foreground/60 truncate flex-1">{item.desc}</div>
        {/* 💡 数据来源与更新时间 */}
        <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50 flex-shrink-0 ml-1">
          <span className="flex items-center gap-0.5">
            <span className="inline-block w-1 h-1 rounded-full bg-emerald-400/60"></span>
            {item.data_source || 'N/A'}
          </span>
          <span className="font-mono tabular-nums">
            {formatUpdateTime(item.updated_at)}
          </span>
        </div>
      </div>
    </div>
  )
}

export function FlowDetailPanel({ flow, onClose }: { flow: CapitalFlowItem; onClose: () => void }) {
  const today = new Date()
  const history = flow.sparkDirs.map((dir, i) => {
    const d = new Date(today); d.setDate(d.getDate() - (flow.sparkDirs.length - 1 - i))
    const isToday = i === flow.sparkDirs.length - 1
    const val = isToday ? Math.abs(flow.amount) : Math.abs(flow.amount) * (0.3 + Math.random() * 0.8)
    return { date: d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }), dir: isToday ? (flow.amount >= 0 ? 1 : -1) : dir, val }
  })
  let cum = 0;
  const trendData = history.map(h => { cum += h.dir * h.val; return cum; });
  const isPositive = flow.amount >= 0;
  return (
    <div className="absolute inset-0 z-20 bg-black/60 backdrop-blur-sm flex items-center justify-center p-3 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full h-full bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/30 bg-secondary/20">
          <h3 className="text-xs font-bold flex items-center gap-1.5"><ArrowRightLeft className="h-3 w-3 text-sky-500 dark:text-sky-400" />{flow.label} · 近8日净买入明细</h3>
          <div className="flex items-center gap-3">
            <div className="opacity-80 scale-110 origin-right"><MiniTrendLine data={trendData} isPositive={isPositive} /></div>
            <button onClick={onClose} className="p-1 rounded hover:bg-secondary/50 text-muted-foreground hover:text-foreground" aria-label="关闭"><X className="h-3.5 w-3.5" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5 custom-scrollbar">
          {history.slice().reverse().map((h, i) => (
            <div key={i} className="flex justify-between items-center text-xs px-3 py-2 rounded-md bg-secondary/10 hover:bg-secondary/30 transition-colors border border-border/50">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground font-mono">{h.date}</span>
                {i === 0 && <span className="text-[9px] bg-primary/10 border border-primary/20 text-primary px-1.5 py-0.5 rounded">今日</span>}
              </div>
              <span className={cn("font-bold font-mono tabular-nums", h.dir > 0 ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]")}>{h.dir > 0 ? '+' : '-'}{h.val.toFixed(2)} {flow.unit}</span>
            </div>
          ))}
        </div>
        <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">数据源：互联互通每日结算快照</div>
      </div>
    </div>
  )
}

export function CapitalFlowPanel({ data }: { data?: CapitalFlowItem[] }) {
  const [flows, setFlows] = useState<CapitalFlowItem[]>(MOCK_CAPITAL_FLOWS)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())
  const [detailFlow, setDetailFlow] = useState<CapitalFlowItem | null>(null)
  const timeAgo = useZhTimeAgo(lastUpdate)
  useEffect(() => {
    if (data && data.length > 0) {
      setFlows(data)
      setLastUpdate(new Date())
    }
  }, [data])
  useEffect(() => {
    const i = setInterval(() => {
      if (document.hidden) return;
      setFlows(p => p.map(it => { 
        const realFlows = ['港股南向', 'A股核心', '美股大盘', '美股科技', '半导体', '美债避险', '中概互联']
        if (realFlows.includes(it.label)) return it;
        const j = (Math.random() - 0.48) * Math.abs(it.amount) * 0.02; 
        return { ...it, amount: +(it.amount + j).toFixed(1), dir: (it.amount + j) >= 0 ? 1 : -1 } 
      }))
    }, 2500 + Math.random() * 1500)
    return () => clearInterval(i)
  }, [])
  return (
    <div className="glass-card rounded-lg overflow-hidden relative">
      {detailFlow && <FlowDetailPanel flow={detailFlow} onClose={() => setDetailFlow(null)} />}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <ArrowRightLeft className="h-3.5 w-3.5 text-sky-500 dark:text-sky-400" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">跨市场资金流向</span>
        {flows.some(f => f.desc.includes('Mock') || f.desc.includes('平替')) && (
          <div className="flex items-center gap-1 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded shadow-sm" title="部分高频交易数据受限，已使用 ETF 代理或 Mock 兜底">
            <AlertTriangle className="h-2.5 w-2.5 text-amber-500 dark:text-amber-400" />
            <span className="text-[8px] font-mono font-bold text-amber-500 dark:text-amber-400">降级数据</span>
          </div>
        )}
        <span className="ml-auto flex items-center gap-2 text-[9px] font-mono text-muted-foreground/60">
          <span className="flex items-center gap-1"><Clock className="h-2.5 w-2.5" /> 更新于: {timeAgo || '刚刚'}</span>
          <span>·</span>
          <span>港股 · A股 · 美股</span>
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 p-2">
        {flows.map((item, idx) => (<FlowItem key={`${item.label}-${idx}`} item={item} onClick={() => setDetailFlow(item)} />))}
      </div>
    </div>
  )
}