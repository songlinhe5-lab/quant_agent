/**
 * AI-01 能力②：形态识别（头肩顶 / 双底 / 三角收敛）
 *
 * 纯函数模块，无 React 依赖。输入为 OHLCV 序列（与 realHistory 结构一致），
 * 输出可被 PROD-02 ChartAnnotationPayload 直接消费的价位线与区域。
 * 历史胜率通过对全量历史做滑动窗口回测得到，避免凭空捏造。
 */

export type PatternType = 'HS_TOP' | 'DOUBLE_BOTTOM' | 'TRIANGLE'
export type PatternBias = 'bullish' | 'bearish' | 'neutral'

export interface PatternLevel {
  price: number
  kind: 'support' | 'resistance' | 'target' | 'stop'
  label: string
}

export interface PatternZone {
  lower: number
  upper: number
}

export interface DetectedPattern {
  type: PatternType
  name: string
  bias: PatternBias
  levels: PatternLevel[]
  zone?: PatternZone
  summary: string
}

export interface Bar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface WinRateResult {
  winRate: number | null
  samples: number
}

function pivots(bars: Bar[], n = 3): { highs: number[]; lows: number[] } {
  const highs: number[] = []
  const lows: number[] = []
  for (let i = n; i < bars.length - n; i++) {
    let isHigh = true
    let isLow = true
    for (let j = i - n; j <= i + n; j++) {
      if (j === i) continue
      if (bars[j].high >= bars[i].high) isHigh = false
      if (bars[j].low <= bars[i].low) isLow = false
    }
    if (isHigh) highs.push(i)
    if (isLow) lows.push(i)
  }
  return { highs, lows }
}

/** 头肩顶：左肩 < 头 > 右肩，双肩近似等高，颈线为两肩间低点的均值。看空。 */
export function detectHeadShouldersTop(bars: Bar[]): DetectedPattern | null {
  const { highs, lows } = pivots(bars, 3)
  if (highs.length < 3 || lows.length < 2) return null
  for (let a = 0; a < highs.length - 2; a++) {
    const i0 = highs[a]
    const i1 = highs[a + 1]
    const i2 = highs[a + 2]
    const h0 = bars[i0].high
    const h1 = bars[i1].high
    const h2 = bars[i2].high
    if (!(h1 > h0 && h1 > h2)) continue
    if (Math.abs(h0 - h2) / h1 > 0.06) continue
    const lA = lows.filter((i) => i > i0 && i < i1)
    const lB = lows.filter((i) => i > i1 && i < i2)
    if (!lA.length || !lB.length) continue
    const neck = (bars[lA[lA.length - 1]].low + bars[lB[0]].low) / 2
    if (i2 < bars.length - 12) continue // 必须贴近右沿（近期形态）
    const target = neck - (h1 - neck)
    return {
      type: 'HS_TOP',
      name: '头肩顶',
      bias: 'bearish',
      levels: [
        { price: round(neck), kind: 'support', label: '颈线' },
        { price: round(target), kind: 'target', label: '目标' },
      ],
      zone: { lower: round(neck), upper: round(h1) },
      summary: `头肩顶成型：左肩 ${h0.toFixed(2)} / 头 ${h1.toFixed(2)} / 右肩 ${h2.toFixed(2)}，颈线 ${neck.toFixed(2)}，理论目标 ${target.toFixed(2)}`,
    }
  }
  return null
}

/** 双底：两段近似等高的低点，中间夹一个峰（颈线）。看多。 */
export function detectDoubleBottom(bars: Bar[]): DetectedPattern | null {
  const { lows, highs } = pivots(bars, 3)
  if (lows.length < 2 || highs.length < 1) return null
  for (let a = 0; a < lows.length - 1; a++) {
    const i0 = lows[a]
    const i1 = lows[a + 1]
    const l0 = bars[i0].low
    const l1 = bars[i1].low
    if (Math.abs(l0 - l1) / ((l0 + l1) / 2) > 0.04) continue
    if (i1 - i0 < 8) continue
    const peak = highs.filter((i) => i > i0 && i < i1)
    if (!peak.length) continue
    const neck = Math.max(...peak.map((i) => bars[i].high))
    if (i1 < bars.length - 12) continue
    const target = neck + (neck - (l0 + l1) / 2)
    return {
      type: 'DOUBLE_BOTTOM',
      name: '双底',
      bias: 'bullish',
      levels: [
        { price: round((l0 + l1) / 2), kind: 'support', label: '双底' },
        { price: round(neck), kind: 'resistance', label: '颈线' },
        { price: round(target), kind: 'target', label: '目标' },
      ],
      zone: { lower: round(Math.min(l0, l1)), upper: round(neck) },
      summary: `双底成型：底1 ${l0.toFixed(2)} / 底2 ${l1.toFixed(2)}，颈线 ${neck.toFixed(2)}，理论目标 ${target.toFixed(2)}`,
    }
  }
  return null
}

/** 三角收敛：上轨（高点）下移、下轨（低点）上移，振幅逐步收窄。中性（方向待突破）。 */
export function detectTriangle(bars: Bar[], window = 40): DetectedPattern | null {
  if (bars.length < window) return null
  const seg = bars.slice(-window)
  const n = seg.length
  const xs = seg.map((_, i) => i)
  const mx = xs.reduce((s, x) => s + x, 0) / n
  const slope = (ys: number[]) => {
    const my = ys.reduce((s, y) => s + y, 0) / n
    let num = 0
    let den = 0
    for (let i = 0; i < n; i++) {
      num += (xs[i] - mx) * (ys[i] - my)
      den += (xs[i] - mx) ** 2
    }
    return den === 0 ? 0 : num / den
  }
  const hiSlope = slope(seg.map((b) => b.high))
  const loSlope = slope(seg.map((b) => b.low))
  if (!(hiSlope < 0 && loSlope > 0)) return null
  const upperFirst = seg[0].high
  const upperLast = seg[n - 1].high
  const lowerFirst = seg[0].low
  const lowerLast = seg[n - 1].low
  if (upperLast >= upperFirst || lowerLast <= lowerFirst) return null
  const gapFirst = upperFirst - lowerFirst
  const gapLast = upperLast - lowerLast
  if (gapFirst <= 0 || gapLast <= 0) return null
  if (gapLast / gapFirst > 0.5) return null // 收敛不足
  return {
    type: 'TRIANGLE',
    name: '三角收敛',
    bias: 'neutral',
    levels: [
      { price: round(upperLast), kind: 'resistance', label: '上轨' },
      { price: round(lowerLast), kind: 'support', label: '下轨' },
    ],
    zone: { lower: round(lowerLast), upper: round(upperLast) },
    summary: `三角收敛：上轨下移斜率 ${hiSlope.toFixed(3)}、下轨上移斜率 ${loSlope.toFixed(3)}，振幅收窄至 ${(gapLast / gapFirst * 100).toFixed(0)}%`,
  }
}

function round(v: number): number {
  return Math.round(v * 100) / 100
}

/** 在最近窗口检测已形成的形态（按优先级返回首个命中）。 */
export function detectLatest(bars: Bar[]): DetectedPattern | null {
  if (bars.length < 30) return null
  const recent = bars.slice(-Math.min(bars.length, 90))
  return (
    detectHeadShouldersTop(recent) ||
    detectDoubleBottom(recent) ||
    detectTriangle(bars)
  )
}

/**
 * 历史胜率回测：在全量历史上以固定窗口滑动，复跑同一检测器，
 * 并在形态窗口之后 horizon 根 K 线内检验是否按预期方向突破/延续。
 */
export function backtestWinRate(
  bars: Bar[],
  type: PatternType,
  horizon = 12,
  win = 60,
): WinRateResult {
  let wins = 0
  let total = 0
  for (let start = 0; start + win <= bars.length; start++) {
    const seg = bars.slice(start, start + win)
    let p: DetectedPattern | null = null
    if (type === 'HS_TOP') p = detectHeadShouldersTop(seg)
    else if (type === 'DOUBLE_BOTTOM') p = detectDoubleBottom(seg)
    else p = detectTriangle(seg)
    if (!p) continue
    const fwd = bars.slice(start + win, start + win + horizon)
    if (fwd.length < Math.ceil(horizon / 2)) continue // 尾部样本不足，跳过
    const trigger = bars[start + win - 1]
    const end = fwd[fwd.length - 1]
    let success = false
    if (type === 'HS_TOP') {
      const neck = p.levels.find((l) => l.kind === 'support')!.price
      success = end.close < neck && end.close < trigger.close
    } else if (type === 'DOUBLE_BOTTOM') {
      const neck = p.levels.find((l) => l.kind === 'resistance')!.price
      success = end.close > neck && end.close > trigger.close
    } else {
      const upper = p.levels.find((l) => l.kind === 'resistance')!.price
      const lower = p.levels.find((l) => l.kind === 'support')!.price
      const breakUp = fwd.some((b) => b.high > upper)
      const breakDown = fwd.some((b) => b.low < lower)
      if (breakUp && !breakDown) success = end.close > upper
      else if (breakDown && !breakUp) success = end.close < lower
    }
    total++
    if (success) wins++
  }
  if (total < 3) return { winRate: null, samples: total }
  return { winRate: wins / total, samples: total }
}
