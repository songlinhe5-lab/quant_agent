'use client'

import { useEffect, useRef } from 'react'
import type { ChartAnnotationPayload } from '@/features/copilot/types'
import { usePatternStore } from '@/stores/usePatternStore'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'
import {
  backtestWinRate,
  detectLatest,
  type Bar,
  type DetectedPattern,
} from './pattern-detect'

function toPayload(symbol: string, p: DetectedPattern, winRate: number | null, samples: number): ChartAnnotationPayload {
  const wr = winRate == null ? '样本不足' : `历史胜率 ${(winRate * 100).toFixed(0)}%（n=${samples}）`
  const biasText = p.bias === 'bullish' ? '看多' : p.bias === 'bearish' ? '看空' : '中性'
  return {
    symbol,
    levels: (p.levels ?? []).map((l) => ({ price: l.price, type: l.kind, label: l.label })),
    zones: p.zone
      ? [{ lower: p.zone.lower, upper: p.zone.upper, label: p.name, color: 'rgba(139,92,246,0.12)' }]
      : undefined,
    note: `${p.name}（${biasText}）· ${p.summary} · ${wr}`,
  }
}

/**
 * AI-01 能力②：形态识别驱动组件（无 UI 渲染，仅计算并写入 usePatternStore）。
 * 监听实时历史 K 线，检测头肩顶/双底/三角收敛并叠加到图表。
 */
export function PatternRecognition({ symbol, history }: { symbol: string; history: Bar[] }) {
  const enabled = usePatternStore((s) => s.enabled)
  const setPattern = usePatternStore((s) => s.setPattern)
  const ai01Enabled = useAiPushPrefStore((s) => s.isEnabled('ai01'))
  const lastKeyRef = useRef('')

  useEffect(() => {
    if (!ai01Enabled || !enabled) {
      setPattern(symbol, null)
      lastKeyRef.current = ''
      return
    }
    const bars = (history || []) as Bar[]
    if (bars.length < 30) {
      setPattern(symbol, null)
      lastKeyRef.current = ''
      return
    }
    const p = detectLatest(bars)
    if (!p) {
      setPattern(symbol, null)
      lastKeyRef.current = ''
      return
    }
    const { winRate, samples } = backtestWinRate(bars, p.type)
    const payload = toPayload(symbol, p, winRate, samples)
    const key = `${symbol}:${p.type}:${(payload.levels ?? []).map((l) => l.price.toFixed(2)).join(',')}`
    if (key !== lastKeyRef.current) {
      lastKeyRef.current = key
      setPattern(symbol, payload, { winRate, samples, patternName: p.name })
    }
  }, [symbol, history, enabled, setPattern])

  return null
}
