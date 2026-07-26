'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useAiNarratorStore } from '@/stores/useAiNarratorStore'

interface BookLevel {
  price: number
  size: number
}

type Tone = 'bull' | 'bear' | 'neutral'

interface BookHint {
  text: string
  tone: Tone
}

// 大单集中判定阈值：单档挂单量 ≥ 该侧中位数的 N 倍，视为异常集中
const CONC_RATIO = 3
// 多空失衡判定阈值：买卖盘总量差占比≥ N，视为显著失衡
const IMB_RATIO = 0.3
// 渲染节流：盘口高频推送，最多每 1.2s 刷新一次文案
const REFRESH_MS = 1200

function toNum(x: unknown): number {
  const n = Number(x)
  return Number.isFinite(n) ? n : 0
}

function normSymbol(s: string): string {
  return s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
}

function levelPrice(l: any): number {
  const p = l?.price ?? (Array.isArray(l) ? l[0] : undefined)
  return toNum(p)
}

function levelSize(l: any): number {
  const s = l?.size ?? l?.volume ?? (Array.isArray(l) ? l[1] : undefined)
  return toNum(s)
}

function parseLevels(raw: any[]): BookLevel[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((l) => ({ price: levelPrice(l), size: levelSize(l) }))
    .filter((l) => l.size > 0)
}

function median(arr: number[]): number {
  if (!arr.length) return 0
  const s = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

function fmtPrice(p: number): string {
  return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtSize(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toLocaleString('en-US')
}

/**
 * AI-01 能力③：盘口大单集中检测。
 * 复用已推送的 Level-2 DOM（market_tick.asks/bids）做纯客户端分析，
 * 在盘口面板底部给出一行提示：超大单压盘/托单、或多空挂单失衡。
 */
function analyze(asks: BookLevel[], bids: BookLevel[]): BookHint | null {
  const aSizes = asks.map((a) => a.size)
  const bSizes = bids.map((b) => b.size)
  if (aSizes.length < 3 || bSizes.length < 3) return null

  const totalAsk = aSizes.reduce((s, x) => s + x, 0)
  const totalBid = bSizes.reduce((s, x) => s + x, 0)
  const total = totalAsk + totalBid
  if (total <= 0) return null

  // 多空挂单失衡比 (-1 ~ 1)
  const imbalance = (totalBid - totalAsk) / total

  // 找该侧最大单档
  const topAsk = asks.reduce((m, x) => (x.size > m.size ? x : m), asks[0])
  const topBid = bids.reduce((m, x) => (x.size > m.size ? x : m), bids[0])
  const aMed = median(aSizes)
  const bMed = median(bSizes)
  const askConc = aMed > 0 ? topAsk.size / aMed : 0
  const bidConc = bMed > 0 ? topBid.size / bMed : 0

  // 优先级：单档大单集中 > 多空失衡 > 均衡
  if (askConc >= CONC_RATIO) {
    const pct = (topAsk.size / totalAsk) * 100
    return {
      tone: 'bear',
      text: `卖盘 $${fmtPrice(topAsk.price)} 现 ${fmtSize(topAsk.size)} 股压单（占卖盘 ${pct.toFixed(0)}%）`,
    }
  }
  if (bidConc >= CONC_RATIO) {
    const pct = (topBid.size / totalBid) * 100
    return {
      tone: 'bull',
      text: `买盘 $${fmtPrice(topBid.price)} 集中 ${fmtSize(topBid.size)} 股托单（占买盘 ${pct.toFixed(0)}%）`,
    }
  }
  if (imbalance >= IMB_RATIO) {
    return {
      tone: 'bull',
      text: `买盘挂单占优（多空比 ${(totalBid / totalAsk).toFixed(2)}），多头挂单意愿强`,
    }
  }
  if (imbalance <= -IMB_RATIO) {
    return {
      tone: 'bear',
      text: `卖盘挂单占优（空多比 ${(totalAsk / totalBid).toFixed(2)}），空头挂单意愿强`,
    }
  }
  return { tone: 'neutral', text: '盘口均衡，多空挂单无明显大单聚集' }
}

export function OrderBookLargeOrderHint({ symbol }: { symbol: string }) {
  const enabled = useAiNarratorStore((s) => s.orderBookAiEnabled)
  const [hint, setHint] = useState<BookHint | null>(null)
  const lastUpdateRef = useRef(0)
  const lastTextRef = useRef('')

  useEffect(() => {
    if (!enabled) {
      setHint(null)
      lastTextRef.current = ''
      return
    }
    const target = normSymbol(symbol)
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (!d) return
      if (normSymbol(d.ticker ?? '') !== target) return
      const now = Date.now()
      if (now - lastUpdateRef.current < REFRESH_MS) return
      lastUpdateRef.current = now

      const asks = parseLevels(d.asks)
      const bids = parseLevels(d.bids)
      const res = analyze(asks, bids)
      const text = res ? `${res.text} · 盘口实时` : ''
      if (text !== lastTextRef.current) {
        lastTextRef.current = text
        setHint(res)
      }
    }
    window.addEventListener('market_tick', handler)
    return () => window.removeEventListener('market_tick', handler)
  }, [symbol, enabled])

  if (!enabled || !hint) return null

  const dotClass =
    hint.tone === 'bull'
      ? 'bg-emerald-400'
      : hint.tone === 'bear'
        ? 'bg-red-400'
        : 'bg-slate-500'
  const textClass =
    hint.tone === 'bull'
      ? 'text-emerald-400'
      : hint.tone === 'bear'
        ? 'text-red-400'
        : 'text-slate-400'

  return (
    <div className="shrink-0 px-3 py-1.5 border-t border-border/40 bg-secondary/10 text-[11px] leading-tight flex items-center gap-1.5">
      <span className={cn('inline-block h-1.5 w-1.5 rounded-full shrink-0', dotClass)} />
      <span className={cn('truncate', textClass)}>{hint.text}</span>
    </div>
  )
}
