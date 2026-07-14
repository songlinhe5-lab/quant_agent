import { useMemo } from 'react'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

export function NavAreaChart({
  data,
  currencySym = '',
}: {
  data: { t: string | number; nav: number }[]
  currencySym?: string
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const up = isDark ? '#34d399' : '#059669'

  const chartRef = useEChart(
    () => {
      if (data.length < 2) return null
      return {
        backgroundColor: 'transparent',
        grid: { top: 4, right: 4, bottom: 4, left: 4 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const v = params[0]?.value
            return `NAV: <b>${currencySym}${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}</b>`
          },
        },
        xAxis: { type: 'category', data: data.map((d) => d.t), show: false },
        yAxis: { type: 'value', scale: true, show: false },
        series: [{
          type: 'line',
          data: data.map((d) => d.nav),
          showSymbol: false,
          lineStyle: { color: up, width: 2 },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0.05, color: isDark ? 'rgba(52,211,153,0.15)' : 'rgba(5,150,105,0.15)' },
                { offset: 0.95, color: 'rgba(52,211,153,0)' },
              ],
            },
          },
        }],
      }
    },
    [data, isDark, up, currencySym],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

// ── RISK-01: 板块暴露横向柱状图 ──────────────────────────────────────────────

export function SectorBarChart({
  data,
}: {
  data: { sector: string; pct: number; market_val: number }[]
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const colors = ['#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1', '#14b8a6']

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      return {
        backgroundColor: 'transparent',
        grid: { top: 4, right: 30, bottom: 4, left: 60 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          backgroundColor: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 10 },
          formatter: (params: any) => {
            const d = data[params[0]?.dataIndex]
            return `<b>${d.sector}</b><br/>占比: ${d.pct}%<br/>市值: $${(d.market_val / 1000).toFixed(1)}K`
          },
        },
        xAxis: { type: 'value', show: false },
        yAxis: {
          type: 'category',
          data: data.map((d) => d.sector),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 9 },
        },
        series: [{
          type: 'bar',
          data: data.map((d, i) => ({ value: d.pct, itemStyle: { color: colors[i % colors.length] } })),
          barMaxWidth: 12,
          label: { show: true, position: 'right', formatter: '{c}%', fontSize: 8, color: isDark ? '#94a3b8' : '#64748b' },
        }],
      }
    },
    [data, isDark],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

// ── RISK-03: 相关性矩阵热力图 ─────────────────────────────────────────────

export function CorrelationHeatmap({
  labels,
  matrix,
}: {
  labels: string[]
  matrix: number[][]
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const chartRef = useEChart(
    () => {
      if (!labels.length || !matrix.length) return null
      const heatData: [number, number, number][] = []
      for (let i = 0; i < labels.length; i++) {
        for (let j = 0; j < labels.length; j++) {
          heatData.push([j, i, matrix[i][j]])
        }
      }
      return {
        backgroundColor: 'transparent',
        grid: { top: 4, right: 4, bottom: 30, left: 50 },
        tooltip: {
          backgroundColor: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 10 },
          formatter: (params: any) => {
            const [x, y, val] = params.data
            return `${labels[y]} × ${labels[x]}<br/><b>${val.toFixed(3)}</b>`
          },
        },
        xAxis: {
          type: 'category', data: labels, splitArea: { show: false },
          axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8, rotate: 30 },
          axisLine: { show: false }, axisTick: { show: false },
        },
        yAxis: {
          type: 'category', data: labels, splitArea: { show: false },
          axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8 },
          axisLine: { show: false }, axisTick: { show: false },
        },
        visualMap: {
          min: -1, max: 1, calculable: false, orient: 'horizontal', left: 'center', bottom: 0,
          itemWidth: 8, itemHeight: 60,
          inRange: { color: isDark ? ['#1e3a5f', '#1e293b', '#7f1d1d'] : ['#dbeafe', '#f8fafc', '#fee2e2'] },
          textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8 },
        },
        series: [{
          type: 'heatmap', data: heatData,
          label: { show: labels.length <= 6, formatter: (p: any) => p.data[2].toFixed(2), fontSize: 7, color: isDark ? '#e2e8f0' : '#334155' },
          itemStyle: { borderColor: isDark ? '#0f172a' : '#ffffff', borderWidth: 1 },
        }],
      }
    },
    [labels, matrix, isDark],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

// ── RISK-05: CVaR 瀑布图 ─────────────────────────────────────────────────

export function CVarWaterfallChart({
  data,
}: {
  data: { symbol: string; cvar_contrib: number }[]
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      return {
        backgroundColor: 'transparent',
        grid: { top: 4, right: 4, bottom: 20, left: 50 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 10 },
          formatter: (params: any) => {
            const d = data[params[0]?.dataIndex]
            return `<b>${d.symbol}</b><br/>CVaR 贡献: ${(d.cvar_contrib * 100).toFixed(3)}%`
          },
        },
        xAxis: {
          type: 'category', data: data.map((d) => d.symbol),
          axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8 },
          axisLine: { lineStyle: { color: isDark ? '#334155' : '#e2e8f0' } },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8, formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
          splitLine: { lineStyle: { color: isDark ? '#1e293b' : '#f1f5f9' } },
        },
        series: [{
          type: 'bar',
          data: data.map((d) => ({
            value: d.cvar_contrib,
            itemStyle: { color: d.cvar_contrib < 0 ? (isDark ? '#ef4444' : '#dc2626') : (isDark ? '#10b981' : '#059669') },
          })),
          barMaxWidth: 20,
        }],
      }
    },
    [data, isDark],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

export function RiskRadarChart({
  data,
}: {
  data: { axis: string; current: number; limit: number }[]
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const indicators = useMemo(() => data.map((d) => ({ name: d.axis, max: 100 })), [data])
  const current = useMemo(() => data.map((d) => d.current), [data])
  const limit = useMemo(() => data.map((d) => d.limit), [data])
  const cur = isDark ? '#34d399' : '#059669'

  const chartRef = useEChart(
    () => {
      if (!indicators.length) return null
      const text = isDark ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)'
      const split = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
      return {
        backgroundColor: 'transparent',
        radar: {
          indicator: indicators,
          splitLine: { lineStyle: { color: split } },
          axisName: { color: text, fontSize: 8 },
          splitArea: { show: false },
          center: ['50%', '55%'],
          radius: '70%',
        },
        series: [{
          type: 'radar',
          data: [
            {
              name: '当前',
              value: current,
              lineStyle: { color: cur, width: 1.5 },
              areaStyle: { color: cur, opacity: 0.12 },
              itemStyle: { color: cur },
            },
            {
              name: '限额',
              value: limit,
              lineStyle: { color: isDark ? 'rgba(239,68,68,0.4)' : 'rgba(220,38,38,0.4)', type: 'dashed', width: 1 },
              areaStyle: { opacity: 0 },
              itemStyle: { color: ECHART_DARK.down },
            },
          ],
        }],
      }
    },
    [indicators, current, limit, isDark, cur],
  )

  return <div ref={chartRef} className="w-full h-full" />
}
