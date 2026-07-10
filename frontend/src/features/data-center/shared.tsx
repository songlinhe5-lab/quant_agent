import React, { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export const FINANCIAL_TERMS = [
  // 中文实体
  '美联储', 'FOMC', '降息', '加息', '利率', 'CPI', 'PPI', 'PCE', '非农', 'GDP', '通胀', '通缩', '央行', '降准',
  '纳斯达克', '标普', '道琼斯', '恒指', '日经', '原油', '黄金', '比特币', '以太坊',
  '多头', '空头', '做多', '做空', '看涨', '看跌', '财报', '营收', '净利润', '超预期', '低于预期', '新高', '新低',
  '上涨', '下跌', '飙升', '暴跌', '美元', '科技',
  // 英文实体 (智能加载单词边界)
  'FED', 'ECB', 'BOJ', 'VIX', 'WTI', 'BTC', 'ETH', 'ETF', 'Long', 'Short', 'Bullish', 'Bearish', 'Surge', 'Plunge',
  'Inflation', 'Deflation', 'Rate Cut', 'Rate Hike', 'Earnings', 'Revenue'
]

const termsPattern = FINANCIAL_TERMS.map(term => {
  return /^[A-Za-z\s]+$/.test(term) ? `\\b${term}\\b` : term
}).join('|')
export const FINANCIAL_REGEX = new RegExp(`(${termsPattern})`, 'gi')

export function getHighlightColor(term: string) {
  const t = term.toLowerCase()
  const bullish = ['多头', '做多', '看涨', '新高', '上涨', '飙升', '超预期', '降息', '降准', 'bullish', 'long', 'surge', 'rate cut']
  const bearish = ['空头', '做空', '看跌', '新低', '下跌', '暴跌', '低于预期', '加息', 'bearish', 'short', 'plunge', 'rate hike']

  if (bullish.includes(t)) return 'text-[#059669] dark:text-[#0ecb81] bg-[#0ecb81]/10'
  if (bearish.includes(t)) return 'text-[#e11d48] dark:text-[#f6465d] bg-[#f6465d]/10'
  return 'text-sky-600 dark:text-sky-400 bg-sky-500/10' // 默认中性蓝色
}

export function HighlightedText({ text }: { text: string }) {
  if (!text) return null
  const parts = text.split(FINANCIAL_REGEX)
  return (
    <>
      {parts.map((part, i) => {
        if (FINANCIAL_TERMS.some(t => t.toLowerCase() === part.toLowerCase())) {
          const colorCls = getHighlightColor(part)
          return (
            <span key={i} className={cn("font-bold px-[3px] py-[1px] mx-[1px] rounded transition-colors", colorCls)}>
              {part}
            </span>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

export function MiniTrendLine({ data, isPositive }: { data: number[], isPositive: boolean }) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  if (!data || data.length === 0) return null
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1
  const pts = data.map((d, i) => `${(i / (data.length - 1)) * 48},${20 - ((d - min) / range) * 16}`).join(' L ')
  return (
    <svg width="48" height="20" viewBox="0 0 48 20" className="overflow-visible" aria-hidden="true">
      <path d={`M ${pts}`} fill="none" stroke={isPositive ? (isDark ? '#0ecb81' : '#059669') : (isDark ? '#f6465d' : '#e11d48')} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function MarketClocks() {
  const [mounted, setMounted] = useState(false)
  const [now, setNow] = useState(new Date())
  useEffect(() => { setMounted(true); const t = setInterval(() => {
    if (!document.hidden) setNow(new Date())
  }, 1000); return () => clearInterval(t) }, [])
  if (!mounted) return null
  const getMarketInfo = (tz: string, oH: number, oM: number, cH: number, cM: number) => {
    const f = new Intl.DateTimeFormat('en-US', { timeZone: tz, hour12: false, hour: '2-digit', minute: '2-digit', weekday: 'short' })
    const p = f.formatToParts(now)
    const h = parseInt(p.find(x => x.type === 'hour')?.value || '0', 10)
    const m = parseInt(p.find(x => x.type === 'minute')?.value || '0', 10)
    const isOpen = !['Sat', 'Sun'].includes(p.find(x => x.type === 'weekday')?.value || '') && (h * 60 + m >= oH * 60 + oM && h * 60 + m < cH * 60 + cM)
    return { time: `${p.find(x => x.type === 'hour')?.value}:${p.find(x => x.type === 'minute')?.value}`, isOpen }
  }
  return (
    <div className="ml-auto flex items-center gap-3">
      {[{ n: 'NY', ...getMarketInfo('America/New_York', 9, 30, 16, 0) }, { n: 'HK', ...getMarketInfo('Asia/Hong_Kong', 9, 30, 16, 0) }, { n: 'TYO', ...getMarketInfo('Asia/Tokyo', 9, 0, 15, 0) }].map(m => (
        <div key={m.n} className="flex items-center gap-1.5" title={m.isOpen ? '交易中' : '已休市'}>
          <span className={cn("h-1.5 w-1.5 rounded-full transition-colors duration-500", m.isOpen ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse" : "bg-muted-foreground/30")} />
          <span className={cn("text-[10px] font-mono tabular-nums transition-colors duration-300", m.isOpen ? "text-foreground font-bold" : "text-muted-foreground")}>{m.n} {m.time}</span>
        </div>
      ))}
    </div>
  )
}

export function AssetButton({ asset }: { asset: any }) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prev = useRef(asset.value)
  const navigate = useNavigate();
  useEffect(() => {
    if (asset.value > prev.current) setFlash('up'); else if (asset.value < prev.current) setFlash('down')
    prev.current = asset.value
    const t = setTimeout(() => setFlash(null), 800); return () => clearTimeout(t)
  }, [asset.value])

  // 💡 格式化更新时间
  const formatUpdateTime = (dateStr: string | null) => {
    if (!dateStr) return '--'
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    } catch {
      return '--'
    }
  }

  return (
    <button onClick={() => navigate(`/market/${asset.symbol}`)}
      className={cn('relative flex flex-col text-left p-2 rounded-xl border border-border/50', 'bg-white dark:bg-secondary/20 hover:bg-secondary/50 dark:hover:bg-secondary/40', 'transition-all outline-none focus-visible:ring-2 focus-visible:ring-primary', 'group shadow-xs hover:shadow-sm overflow-hidden', flash === 'up' && 'animate-flash-green', flash === 'down' && 'animate-flash-red')} title={`查看 ${asset.name} 详情`}>
      <div className="flex items-start justify-between w-full mb-1.5">
        <div className="flex flex-col min-w-0 mr-2 text-left">
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-bold text-muted-foreground/70 group-hover:text-muted-foreground uppercase tracking-wider">{asset.symbol}</span>
            {asset.source === 'fred' && (
              <span className="text-[7px] font-bold bg-indigo-500/10 text-indigo-500 dark:text-indigo-400 border border-indigo-500/20 px-1 py-[1px] rounded-sm leading-none" title="当前数据由 FRED 降级兜底提供">FRED</span>
            )}
          </div>
          <span className="text-xs font-bold text-foreground/90 mt-0.5 truncate">{asset.name}</span>
        </div>
        <div className={cn('px-1.5 py-0.5 rounded-md flex items-center gap-0.5 text-[9px] font-mono font-bold flex-shrink-0', asset.change >= 0 ? 'bg-[#0ecb81]/15 text-[#059669] dark:text-[#0ecb81]' : 'bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]')}>
          {asset.change >= 0 ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}{asset.change >= 0 ? '+' : ''}{asset.change.toFixed(2)}%
        </div>
      </div>
      <div className="flex items-end justify-between w-full mt-auto">
        <span className={cn('text-sm font-bold font-mono tabular-nums tracking-tight transition-colors duration-500', flash === 'up' ? 'text-[#059669] dark:text-[#0ecb81]' : flash === 'down' ? 'text-[#e11d48] dark:text-[#f6465d]' : 'text-foreground')}>
          {asset.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        {asset.sparkline && <div className="opacity-60 group-hover:opacity-100 transition-opacity flex-shrink-0"><MiniTrendLine data={asset.sparkline} isPositive={asset.change >= 0} /></div>}
      </div>
      {/* 💡 数据来源与更新时间 */}
      <div className="mt-1.5 pt-1 border-t border-border/10">
        <div className="flex items-center justify-between text-[8px] text-muted-foreground/50">
          <span className="flex items-center gap-0.5">
            <span className="inline-block w-1 h-1 rounded-full bg-emerald-400/60"></span>
            {asset.data_source || 'YFinance'}
          </span>
          <span className="font-mono tabular-nums">
            {formatUpdateTime(asset.updated_at)}
          </span>
        </div>
      </div>
    </button>
  )
}

export const NEWS_TAG_COLORS: Record<string, string> = {
  FED: 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30',
  ECB: 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30',
  BOJ: 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30',
  INFLATION: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  ECONOMY: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  CRYPTO: 'bg-violet-500/15 text-violet-600 dark:text-violet-400 border-violet-500/30',
  COMMODITY: 'bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30',
  GEOPOLITICS: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
}

export function playAlertSound() {
  try {
    const AudioContext = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioContext) return
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gainNode = ctx.createGain()

    osc.type = 'triangle' // 三角波，声音有穿透力且不刺耳
    osc.frequency.setValueAtTime(800, ctx.currentTime) // 高音调
    osc.frequency.exponentialRampToValueAtTime(300, ctx.currentTime + 0.15) // 快速降频产生打击感

    gainNode.gain.setValueAtTime(0.4, ctx.currentTime)
    gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3) // 300ms 快速淡出

    osc.connect(gainNode)
    gainNode.connect(ctx.destination)

    osc.start()
    osc.stop(ctx.currentTime + 0.3)
  } catch (e) {
    console.warn('播放提示音失败(可能需要用户先与页面交互):', e)
  }
}
