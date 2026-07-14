import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

export type HistogramBin = {
  range: string
  count: number
  percent?: number
  color: string
  lightColor: string
}

/** Daily returns distribution histogram (ECharts). */
export function ReturnsHistogramChart({ data }: { data: HistogramBin[] }) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const text = isDark ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)'
      const split = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
      return {
        backgroundColor: 'transparent',
        grid: { top: 16, right: 12, bottom: 28, left: 40 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const p = params[0]
            const bin = data[p.dataIndex]
            const pct = bin?.percent != null ? ` (占 ${bin.percent}%)` : ''
            return `${p.name}<br/>发生频次: <b>${p.value}</b> 天${pct}`
          },
        },
        xAxis: {
          type: 'category',
          data: data.map((d) => d.range),
          axisLabel: { color: text, fontSize: 9 },
          axisLine: { lineStyle: { color: split } },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: text, fontSize: 10 },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
        },
        series: [{
          type: 'bar',
          data: data.map((d) => ({
            value: d.count,
            itemStyle: { color: isDark ? d.color : d.lightColor, opacity: 0.8, borderRadius: [2, 2, 0, 0] },
          })),
          barMaxWidth: 36,
        }],
      }
    },
    [data, isDark],
  )

  return <div ref={chartRef} className="w-full h-full" />
}
