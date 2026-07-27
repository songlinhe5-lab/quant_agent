'use client'

import { useEffect, useRef, useState } from 'react'
import { Sparkles, AlertTriangle, RefreshCw } from 'lucide-react'

import { apiClient } from '@/lib/api-client'
import { usePatternStore } from '@/stores/usePatternStore'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'

const AI02_THRESHOLD = 2.0

const cleanSym = (s: string) =>
  s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')

interface CoPilotRequest {
  symbol: string
  change_pct: number
  direction?: 'up' | 'down'
  threshold?: number
  include_pattern_winrate?: boolean
  pattern_winrate?: number | null
  pattern_name?: string | null
}

interface DonePayload {
  symbol: string
  summary: string
  source: string
  confidence: number
  pattern_winrate?: number | null
}

/**
 * AI-02 解盘副驾：订阅 /ai/stream NDJSON 流，回显流式解说。
 * - 受 useAiPushPrefStore.isEnabled('ai02') 控制（Phase 0 基座）
 * - 复用 AnomalyFlash 同款 quote_update / market_tick 信号，异动达标自动开流；亦支持手动「重新解盘」
 * - 首屏骨架屏占位，禁止编造 '正在分析' 之类假文案
 */
export function CoPilotPanel({ symbol }: { symbol: string }) {
  const ai02Enabled = useAiPushPrefStore((s) => s.isEnabled('ai02'))
  const patternWinRate = usePatternStore((s) => s.winRate)
  const patternName = usePatternStore((s) => s.patternName)

  const [text, setText] = useState('')
  const [done, setDone] = useState<DonePayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)

  const latestRef = useRef<{ pct: number; dir: 'up' | 'down' } | null>(null)
  const streamingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  const run = (pct: number, dir: 'up' | 'down') => {
    if (streamingRef.current) return
    streamingRef.current = true
    setStreaming(true)
    setText('')
    setDone(null)
    setError(null)

    const controller = new AbortController()
    abortRef.current = controller

    const body: CoPilotRequest = {
      symbol,
      change_pct: pct,
      direction: dir,
      threshold: AI02_THRESHOLD,
      include_pattern_winrate: patternWinRate != null,
      pattern_winrate: patternWinRate ?? null,
      pattern_name: patternName ?? null,
    }

    void (async () => {
      try {
        const res = await apiClient.stream('/ai/stream', body, controller.signal)
        if (!res.body) throw new Error('空响应')
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done: d, value } = await reader.read()
          if (d) break
          buf += decoder.decode(value, { stream: true })
          let nl: number
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim()
            buf = buf.slice(nl + 1)
            if (!line) continue
            const evt = JSON.parse(line) as { event: string; data?: unknown }
            if (evt.event === 'ping') {
              // 占位首包，已在 setStreaming(true)
            } else if (evt.event === 'delta') {
              const data = evt.data as { text?: string }
              if (data?.text) setText((t) => t + data.text)
            } else if (evt.event === 'done') {
              setDone(evt.data as DonePayload)
              setStreaming(false)
            } else if (evt.event === 'error') {
              setError(String(evt.data ?? '解说异常'))
              setStreaming(false)
            }
          }
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setError('解说流中断')
          setStreaming(false)
        }
      } finally {
        streamingRef.current = false
      }
    })()
  }

  useEffect(() => {
    if (!ai02Enabled || !symbol) return
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (!d?.ticker || cleanSym(String(d.ticker)) !== cleanSym(symbol)) return
      const raw = String(d.change_pct ?? '0').replace('%', '')
      const pct = parseFloat(raw) || 0
      const dir: 'up' | 'down' = pct >= 0 ? 'up' : 'down'
      latestRef.current = { pct, dir }
      if (Math.abs(pct) >= AI02_THRESHOLD) run(pct, dir)
    }
    window.addEventListener('market_tick', handler)
    window.addEventListener('quote_update', handler)
    return () => {
      window.removeEventListener('market_tick', handler)
      window.removeEventListener('quote_update', handler)
      abortRef.current?.abort()
    }
  }, [ai02Enabled, symbol])

  if (!ai02Enabled) return null

  return (
    <div className="glass-panel rounded-xl p-4 border border-indigo-400/20">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-indigo-300 text-sm font-medium">
          <Sparkles className="w-4 h-4" />
          解盘副驾
        </div>
        <button
          type="button"
          onClick={() => {
            const l = latestRef.current
            if (l) run(l.pct, l.dir)
          }}
          disabled={streaming || !latestRef.current}
          className="text-xs px-2 py-1 rounded-lg bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-40 flex items-center gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${streaming ? 'animate-spin' : ''}`} />
          重新解盘
        </button>
      </div>

      <div className="text-sm text-slate-200 leading-relaxed min-h-[3rem]">
        {streaming && !text ? (
          <span className="block h-4 w-2/3 bg-slate-600/40 rounded animate-pulse" />
        ) : text ? (
          text
        ) : (
          <span className="text-slate-500">等待异动信号…</span>
        )}
      </div>

      {error && (
        <div className="mt-2 flex items-center gap-1 text-xs text-red-400">
          <AlertTriangle className="w-3 h-3" />
          {error}
        </div>
      )}

      {done && (
        <div className="mt-2 pt-2 border-t border-slate-700/50 text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
          <span>来源：{done.source}</span>
          <span>置信度：{(done.confidence * 100).toFixed(0)}%</span>
          {done.pattern_winrate != null && (
            <span>形态胜率：{(done.pattern_winrate * 100).toFixed(0)}%</span>
          )}
        </div>
      )}
    </div>
  )
}
