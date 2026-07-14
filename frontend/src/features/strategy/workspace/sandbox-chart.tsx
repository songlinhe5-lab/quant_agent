import { useRef, useEffect } from 'react'
import { createChart, ColorType, LineStyle, IChartApi, ISeriesApi, SeriesMarker, LineSeries, AreaSeries } from 'lightweight-charts'
import { useTheme } from 'next-themes'

/** Sandbox equity / price chart with trade markers and limit-order overlays. */
export function SandboxChart({
  data,
  trades = [],
  limitOrders = [],
  onLimitOrderClick,
  selectedLimitOrderIdx,
}: {
  data: any[]
  trades?: any[]
  limitOrders?: any[]
  onLimitOrderClick?: (order: any, idx: number) => void
  selectedLimitOrderIdx?: number | null
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const limitSeriesRefs = useRef<ISeriesApi<'Line'>[]>([])
  const { theme } = useTheme()
  const onLimitOrderClickRef = useRef(onLimitOrderClick)

  useEffect(() => {
    onLimitOrderClickRef.current = onLimitOrderClick
  }, [onLimitOrderClick])

  useEffect(() => {
    if (!chartContainerRef.current || !data || data.length === 0) return

    const isDark = theme === 'dark'
    const textColor = isDark ? '#94a3b8' : '#64748b'
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: textColor,
      },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      rightPriceScale: { borderColor: gridColor },
      timeScale: { borderColor: gridColor, timeVisible: true, fixLeftEdge: true, fixRightEdge: true },
    })
    chartRef.current = chart

    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: '#8b5cf6', lineWidth: 2, lineStyle: LineStyle.Dashed, title: '基准(标的)',
    })
    benchmarkSeries.setData(data.map(d => ({ time: d.date, value: d.benchmark })))

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor: '#10b981', topColor: 'rgba(16, 185, 129, 0.3)', bottomColor: 'rgba(16, 185, 129, 0.01)', lineWidth: 2, title: '策略净值',
    })
    equitySeries.setData(data.map(d => ({ time: d.date, value: d.equity })))

    const priceSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.5)', lineWidth: 1, title: '标的价格', priceScaleId: 'price',
    })
    chart.priceScale('price').applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } })
    priceSeries.setData(data.map(d => ({ time: d.date, value: d.price || d.benchmark })))

    const globalMarkers: SeriesMarker<any>[] = []

    if (trades && trades.length > 0) {
      trades.forEach((trade) => {
        let color = ''
        let shape: SeriesMarker<any>['shape'] = 'circle'
        let position: SeriesMarker<any>['position'] = 'inBar'
        let text = ''

        if (trade.action === 'BUY' || trade.action === 'COVER') {
          color = '#10b981'
          shape = 'arrowUp'
          position = 'belowBar'
          text = '买'
        } else if (trade.action === 'SELL' || trade.action === 'SHORT') {
          color = '#ef4444'
          shape = 'arrowDown'
          position = 'aboveBar'
          text = '卖'
        }

        if (color) {
          globalMarkers.push({ time: trade.date, position, color, shape, text, size: 1 })
        }
      })
    }

    if (limitOrders && limitOrders.length > 0) {
      limitOrders.forEach(order => {
        const limitLine = chart.addSeries(LineSeries, {
          color: 'rgba(245, 158, 11, 0.8)', lineWidth: 2, lineStyle: LineStyle.Dotted, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceScaleId: 'price',
        })
        limitSeriesRefs.current.push(limitLine)
        limitLine.setData([{ time: order.start_date, value: order.price }, { time: order.end_date, value: order.price }])

        globalMarkers.push({ time: order.start_date, position: 'inBar', color: '#f59e0b', shape: 'circle', text: `🪝 挂单 @ ${order.price.toFixed(2)}` })

        let statusColor = '#64748b'
        let statusShape: SeriesMarker<any>['shape'] = 'circle'
        let statusText = '挂起中'

        if (order.status === 'FILLED') {
          statusColor = '#10b981'; statusShape = 'arrowUp'; statusText = '⚡ 成交'
        } else if (order.status === 'CANCELED') {
          statusColor = '#ef4444'; statusShape = 'arrowDown'; statusText = '❌ 撤单'
        }
        globalMarkers.push({ time: order.end_date, position: order.status === 'FILLED' ? 'belowBar' : 'aboveBar', color: statusColor, shape: statusShape, text: statusText })
      })
    }

    if (globalMarkers.length > 0) {
      globalMarkers.sort((a, b) => new Date(a.time as string).getTime() - new Date(b.time as string).getTime())
      ;(priceSeries as any).setMarkers(globalMarkers)
    }

    chart.subscribeClick((param) => {
      if (!param.point) return
      const point = param.point
      let closestIdx = -1
      let minDistance = Infinity

      limitOrders.forEach((order, idx) => {
        const series = limitSeriesRefs.current[idx]
        if (!series) return
        const y = series.priceToCoordinate(order.price)
        const x1 = chart.timeScale().timeToCoordinate(order.start_date)
        const x2 = chart.timeScale().timeToCoordinate(order.end_date)
        if (y !== null && x1 !== null && x2 !== null) {
          const minX = Math.min(x1 as number, x2 as number)
          const maxX = Math.max(x1 as number, x2 as number)
          if (point.x >= minX - 15 && point.x <= maxX + 15) {
            const dist = Math.abs(point.y - y)
            if (dist < 15 && dist < minDistance) {
              minDistance = dist
              closestIdx = idx
            }
          }
        }
      })
      if (onLimitOrderClickRef.current) {
        onLimitOrderClickRef.current(closestIdx !== -1 ? limitOrders[closestIdx] : null, closestIdx)
      }
    })

    chart.timeScale().fitContent()
    const handleResize = () => {
      if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
      limitSeriesRefs.current = []
    }
  }, [data, limitOrders, theme, trades])

  useEffect(() => {
    limitSeriesRefs.current.forEach((series, idx) => {
      series.applyOptions({
        color: selectedLimitOrderIdx === idx ? 'rgba(245, 158, 11, 1)' : 'rgba(245, 158, 11, 0.8)',
        lineWidth: selectedLimitOrderIdx === idx ? 3 : 2,
      })
    })
  }, [selectedLimitOrderIdx])

  return <div ref={chartContainerRef} className="w-full h-[260px] mt-2 rounded-xl overflow-hidden border border-border/20 shadow-inner" />
}
