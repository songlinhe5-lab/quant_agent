'use client'

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineSeries } from 'lightweight-charts'

interface HighFreqChartWrapperProps {
  symbol: string
  /** 行情参考价（用于无 tick 数据时锚定 Y 轴与显示参考基线） */
  referencePrice?: number | null
  /** 参考价标签（如 '前收' / '现价'） */
  referenceLabel?: string
  /** 交易时区：HKT(港股)/ET(美股)/CT(大宗商品) */
  marketTz?: 'HKT' | 'ET' | 'CT' | 'UTC'
}

const TZ_OFFSET_HOURS: Record<string, number> = {
  HKT: 8,   // Asia/Hong_Kong (UTC+8)
  ET: -5,   // America/New_York EST (UTC-5)
  CT: -6,   // America/Chicago CST (UTC-6)
  UTC: 0,
}

// 💡 美东夏令时判定 (与主图 K 线一致: 3月第二个周日 ~ 11月第一个周日)
function isUSDST(year: number, month1to12: number, day: number): boolean {
  const firstSundayOfMarch = ((8 - new Date(Date.UTC(year, 2, 1)).getUTCDay()) % 7) || 7
  const secondSundayOfMarch = firstSundayOfMarch + 7
  const firstSundayOfNov = ((8 - new Date(Date.UTC(year, 10, 1)).getUTCDay()) % 7) || 7
  const target = new Date(Date.UTC(year, month1to12 - 1, day)).getTime()
  const dstStart = new Date(Date.UTC(year, 2, secondSundayOfMarch, 2)).getTime()
  const dstEnd = new Date(Date.UTC(year, 10, firstSundayOfNov, 2)).getTime()
  return target >= dstStart && target < dstEnd
}

// 💡 ET 分夏令时 (UTC-4) / 冬令时 (UTC-5); 其余时区固定偏移
function getOffsetHours(tz: keyof typeof TZ_OFFSET_HOURS, date: Date): number {
  if (tz === 'ET') {
    return isUSDST(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()) ? -4 : -5
  }
  return TZ_OFFSET_HOURS[tz] ?? 0
}

const MARKET_SESSION: Record<string, { start: [number, number]; end: [number, number] }> = {
  HKT: { start: [9, 30], end: [16, 0] },     // 港股 09:30-16:00
  ET:  { start: [9, 30], end: [16, 0] },     // 美股 09:30-16:00
  CT:  { start: [8, 30], end: [15, 0] },     // 大宗商品期货日盘
}

// 💡 港股午休 12:00-13:00（当地时），Tick/分时 X 轴需扣除：下午时段时间戳整体前移 1h，使午休从轴消失
const LUNCH_BREAK: Record<string, { resume: [number, number]; seconds: number }> = {
  HKT: { resume: [13, 0], seconds: 3600 },
}
const LUNCH_SECONDS = 3600

// 💡 把交易所当地时刻压缩掉午休：当地 >= 13:00 的时间戳减 3600s，使 12:00 之后紧贴 13:00，X 轴无空洞
function compressLunchBreak(tz: keyof typeof TZ_OFFSET_HOURS, utcSec: number): number {
  const lb = LUNCH_BREAK[tz]
  if (!lb) return utcSec
  const offset = getOffsetHours(tz, new Date(utcSec * 1000))
  const local = new Date((utcSec + offset * 3600) * 1000)
  const lh = local.getUTCHours()
  const lm = local.getUTCMinutes()
  const cmp = lh * 60 + lm
  const resumeCmp = lb.resume[0] * 60 + lb.resume[1]
  return cmp >= resumeCmp ? utcSec - LUNCH_SECONDS : utcSec
}

function utcSecondsInMarketDay(now: Date, tz: keyof typeof TZ_OFFSET_HOURS): { from: number; to: number } {
  const offset = getOffsetHours(tz, now)
  const session = MARKET_SESSION[tz] ?? MARKET_SESSION.ET
  // 先把 UTC 时刻转换为交易所当地日期 (now + offset 小时), 再在该当地日上构造交易时段
  const local = new Date(now.getTime() + offset * 3600 * 1000)
  const ly = local.getUTCFullYear()
  const lm = local.getUTCMonth()
  const ld = local.getUTCDate()
  // 当地 HH:mm → 对应 UTC 秒 = Date.UTC(当地日, 当地start - offset)
  const startHourUTC = session.start[0] - offset
  const endHourUTC = session.end[0] - offset
  let from = Math.floor(Date.UTC(ly, lm, ld, startHourUTC, session.start[1]) / 1000)
  let to = Math.floor(Date.UTC(ly, lm, ld, endHourUTC, session.end[1]) / 1000)
  // 💡 港股午休压缩：收盘端整体前移 1h（16:00 → 15:00），使可见范围终点贴合压缩后的轴
  const lb = LUNCH_BREAK[tz]
  if (lb) to -= lb.seconds
  return { from, to }
}

// 💡 把 UTC 时间戳格式化为交易所当地 HH:mm (tickMarkFormatter 用, 避免刻度偏时区)
//    港股下午段已被压缩 1h,这里还原(+1h)使刻度显示真实 13:00-16:00,与"扣除午休"的轴一致
function formatMarketLocalHM(time: number, tz: keyof typeof TZ_OFFSET_HOURS): string {
  const lb = LUNCH_BREAK[tz]
  const displayTime = lb ? time + lb.seconds : time
  const offset = getOffsetHours(tz, new Date(displayTime * 1000))
  const d = new Date((displayTime + offset * 3600) * 1000)
  const hh = d.getUTCHours().toString().padStart(2, '0')
  const mm = d.getUTCMinutes().toString().padStart(2, '0')
  return `${hh}:${mm}`
}

export function HighFreqChartWrapper({
  symbol,
  referencePrice = null,
  referenceLabel: _referenceLabel = '现价',
  marketTz = 'ET',
}: HighFreqChartWrapperProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null)
  const hasSetRangeRef = useRef(false)
  const anchorPriceRef = useRef<number | null>(null)

  useEffect(() => {
    if (!chartContainerRef.current) return

    const session = utcSecondsInMarketDay(new Date(), marketTz)

    // 1. 初始化纯 Canvas 图表 (零 DOM 开销)
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255, 255, 255, 0.08)' }, horzLines: { color: 'rgba(255, 255, 255, 0.08)' } },
      rightPriceScale: {
        borderColor: '#475569',
        autoScale: true,
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
      timeScale: {
        borderColor: '#475569',
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: false,
        rightOffset: 8,
        barSpacing: 4,
        minBarSpacing: 3,
        maxBarSpacing: 6,
        // 💡 强制 tickMarkFormatter 显示交易所当地 HH:mm 时间刻度 (按 marketTz 折算, 非 UTC)
        tickMarkFormatter: (time: number) => formatMarketLocalHM(time, marketTz),
      },
      crosshair: {
        // 💡 关闭内置 crosshair,父容器自己绘制,避免与父 crosshair 双重叠
        mode: 0 /* CrosshairMode.Hidden (lightweight-charts v5 用 enum, 这里传 0 保险) */,
        vertLine: { visible: false, labelVisible: false },
        horzLine: { visible: false, labelVisible: false },
      },
    })
    chartRef.current = chart

    const lineSeries = chart.addSeries(LineSeries, {
      color: '#10b981',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      // 💡 Y 轴自适应该 series,允许 ±0.5% 视野
    })
    lineSeriesRef.current = lineSeries
    hasSetRangeRef.current = false

    // 2. 如果有参考价（现价/前收）且还没 tick,把参考价当作"伪锚点"画一条水平线 + 立即设可见范围
    if (referencePrice && referencePrice > 0) {
      anchorPriceRef.current = referencePrice
      const anchorTime = compressLunchBreak(marketTz, Math.floor(Date.now() / 1000))
      try {
        lineSeries.update({ time: anchorTime as any, value: referencePrice })
        // 立刻设可见范围,避免等真实 tick
        chart.timeScale().setVisibleRange({
          from: session.from as any,
          to: session.to as any,
        })
        hasSetRangeRef.current = true
      } catch {
        // 静默:无数据时 setVisibleRange 可能 null
      }
    }

    // 3. 监听底层 WebSocket Event Bus
    const handleTick = (e: Event) => {
      const detail = (e as CustomEvent).detail
      const cleanTicker = (s: string) =>
        s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
      if (cleanTicker(detail.ticker) === cleanTicker(symbol) && lineSeriesRef.current) {
        const lastPrice = parseFloat(detail.last_price)
        if (lastPrice > 0) {
          // 💡 港股午休压缩：下午段时间戳减 1h，使午休从 X 轴消失
          const rawSec = Math.floor(Date.now() / 1000)
          lineSeriesRef.current.update({
            time: compressLunchBreak(marketTz, rawSec) as any,
            value: lastPrice,
          })
          // 💡 首个 tick 到达后再次设置全天范围(应对外部参考价缺失)
          if (!hasSetRangeRef.current && chartRef.current) {
            hasSetRangeRef.current = true
            try {
              chartRef.current.timeScale().setVisibleRange({
                from: session.from as any,
                to: session.to as any,
              })
            } catch {
              /* 静默 */
            }
          }
        }
      }
    }

    window.addEventListener('market_tick', handleTick)

    return () => {
      window.removeEventListener('market_tick', handleTick)
      chart.remove()
    }
  }, [symbol, referencePrice, marketTz])

  return (
    <div
      ref={chartContainerRef}
      className="w-full h-full min-h-[300px]"
      suppressHydrationWarning
    />
  )
}
