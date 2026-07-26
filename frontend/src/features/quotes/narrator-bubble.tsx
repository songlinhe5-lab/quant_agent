'use client'

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles, X } from 'lucide-react'

import { apiClient } from '@/lib/api-client'
import { useAiNarratorStore } from '@/stores/useAiNarratorStore'
import { usePatternStore } from '@/stores/usePatternStore'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'
import { cn } from '@/lib/utils'

const cleanSym = (s: string) =>
  s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')

interface NarrativePayload {
  symbol: string
  direction: string
  change_pct: number
  threshold: number
  summary: string
  source: string
  confidence: number
  triggered_by: string
  pattern_winrate?: number | null
}

/**
 * AI-01 异动解说气泡：复用 AnomalyFlash 同款 quote_update / market_tick 信号，
 * 当涨跌幅突破阈值(默认>2%)且开关开启时，调用后端 /ai/narrate 获取一句话数据驱动解说，
 * 浮动于 K 线上方。可折叠、带来源与置信度（可关闭由设置开关控制）。
 */
export function NarratorBubble({ symbol }: { symbol: string }) {
  const { enabled, threshold } = useAiNarratorStore()
  const [visible, setVisible] = useState(false)
  const [dir, setDir] = useState<'up' | 'down'>('up')
  const [data, setData] = useState<NarrativePayload | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const lastKeyRef = useRef<string>('')

  useEffect(() => {
    if (!enabled) {
      setVisible(false)
      setData(null)
      return
    }
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (!d?.ticker || cleanSym(String(d.ticker)) !== cleanSym(symbol)) return
      const raw = String(d.change_pct ?? '0').replace('%', '')
      const pct = parseFloat(raw) || 0
      const over = Math.abs(pct) >= threshold
      if (!over) {
        setVisible(false)
        setData(null)
        setDismissed(false)
        return
      }
      setDir(pct >= 0 ? 'up' : 'down')
      setVisible(true)
      const key = `${symbol}:${pct.toFixed(2)}:${threshold}`
      if (key === lastKeyRef.current) return
      lastKeyRef.current = key
      setDismissed(false)
      setLoading(true)
      apiClient
        .post('/ai/narrate', {
          symbol,
          change_pct: pct,
          direction: pct >= 0 ? 'up' : 'down',
          threshold,
        })
        .then((res: any) => {
          // 兼容两种返回结构：标准 {code,data} 解包后 res.data=result；
          // 非标准 {status,data} 解包后 res.data={status,data}，内层在 res.data.data
          const body = res?.data
          const payload: NarrativePayload =
            body && typeof body === 'object' && body.data && typeof body.data === 'object'
              ? body.data
              : body
          setData(payload)
        })
        .catch(() => {
          setData({
            symbol,
            direction: pct >= 0 ? 'up' : 'down',
            change_pct: pct,
            threshold,
            summary: '解说服务暂时不可用，异动仍可关注',
            source: '本地兜底',
            confidence: 0,
            triggered_by: 'price_anomaly',
          })
        })
        .finally(() => setLoading(false))
    }
    window.addEventListener('market_tick', handler)
    window.addEventListener('quote_update', handler)
    return () => {
      window.removeEventListener('market_tick', handler)
      window.removeEventListener('quote_update', handler)
    }
  }, [symbol, threshold, enabled])

  if (!enabled || !visible || dismissed) return null

  const accent = dir === 'up' ? 'text-emerald-400' : 'text-red-400'

  return (
    <div className="absolute top-12 right-3 z-30 w-[min(88%,520px)]">
      <div className="rounded-lg border border-slate-600/60 bg-slate-900/85 px-3 py-2 shadow-xl backdrop-blur">
        <div className="flex items-start gap-2">
          <Sparkles className={cn('mt-0.5 h-4 w-4 shrink-0', accent)} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={cn('text-xs font-semibold', accent)}>
                {dir === 'up' ? '▲' : '▼'} {Math.abs(data?.change_pct ?? 0).toFixed(2)}%
              </span>
              <span className="text-[10px] text-slate-400">AI 异动解说</span>
              <button
                type="button"
                onClick={() => setCollapsed((c) => !c)}
                className="ml-auto text-slate-400 hover:text-slate-200"
                aria-label="折叠"
              >
                {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
              </button>
              <button
                type="button"
                onClick={() => setDismissed(true)}
                className="text-slate-400 hover:text-slate-200"
                aria-label="关闭"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            {!collapsed && (
              <p className="mt-1 line-clamp-2 text-xs leading-snug text-slate-100">
                {loading ? '正在生成解说…' : data?.summary}
              </p>
            )}
            {!collapsed && data && (
              <p className="mt-1 text-[10px] text-slate-500">
                来源: {data.source} · 置信度 {(data.confidence * 100).toFixed(0)}%
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
