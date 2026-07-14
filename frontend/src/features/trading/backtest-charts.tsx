import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import { ReturnsHistogramChart, type HistogramBin } from '@/features/strategy/workspace/returns-histogram-chart'

type EquityPoint = {
  t: number | string
  date?: string
  strategy: number
  benchmark: number
  drawdownRange?: [number, number]
  tradeAction?: string
  tradeProfit?: number
}

export function BacktestEquityChart({ data }: { data: EquityPoint[] }) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const split = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
      const tradeMarks = data
        .map((d, i) => (d.tradeAction ? { coord: [i, d.strategy], action: d.tradeAction, profit: d.tradeProfit } : null))
        .filter(Boolean) as { coord: [number, number]; action: string; profit?: number }[]

      return {
        backgroundColor: 'transparent',
        grid: { top: 12, right: 12, bottom: 12, left: 12 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const idx = params[0]?.dataIndex ?? 0
            const row = data[idx]
            const date = row?.date || row?.t
            const lines = [`${date}`]
            for (const p of params) {
              if (p.seriesName === '回撤带') continue
              const v = Array.isArray(p.value) ? p.value[1] : p.value
              let extra = ''
              if (p.seriesName === '策略' && row?.tradeAction) {
                const actionStr = row.tradeAction === 'BUY' ? '买入' : '平仓'
                const pnl = row.tradeProfit != null
                  ? ` (${row.tradeProfit > 0 ? '+' : ''}${row.tradeProfit.toFixed(2)})`
                  : ''
                extra = ` [${actionStr}${pnl}]`
              }
              lines.push(`${p.marker}${p.seriesName}: <b>$${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}</b>${extra}`)
            }
            if (row?.drawdownRange) {
              const [lo, hi] = row.drawdownRange
              const dd = ((lo - hi) / hi) * 100
              lines.push(`实时回撤: <b>${dd.toFixed(2)}%</b>`)
            }
            return lines.join('<br/>')
          },
        },
        xAxis: { type: 'category', data: data.map((_, i) => i), show: false },
        yAxis: { type: 'value', scale: true, show: false },
        series: [
          {
            name: '回撤带',
            type: 'line',
            data: data.map((d) => (d.drawdownRange ? d.drawdownRange[0] : null)),
            showSymbol: false,
            lineStyle: { opacity: 0 },
            areaStyle: { color: isDark ? 'rgba(246,70,93,0.15)' : 'rgba(225,29,72,0.15)' },
            stack: undefined,
            z: 1,
          },
          {
            name: '策略',
            type: 'line',
            data: data.map((d) => d.strategy),
            showSymbol: false,
            lineStyle: { color: isDark ? '#34d399' : '#059669', width: 1.5 },
            z: 3,
            markPoint: tradeMarks.length
              ? {
                  symbolSize: 10,
                  data: tradeMarks.map((m) => ({
                    name: m.action,
                    coord: m.coord,
                    itemStyle: { color: m.action === 'BUY' ? ECHART_DARK.up : ECHART_DARK.down },
                    symbol: m.action === 'BUY' ? 'triangle' : 'pin',
                  })),
                }
              : undefined,
          },
          {
            name: '基准',
            type: 'line',
            data: data.map((d) => d.benchmark),
            showSymbol: false,
            lineStyle: { color: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)', width: 1, type: 'dashed' },
            z: 2,
          },
        ],
      }
    },
    [data, isDark],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

export function BacktestUnderwaterChart({
  data,
  maxDrawdown,
}: {
  data: { t: number | string; dd: number }[]
  maxDrawdown?: string
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const maxDd = parseFloat(maxDrawdown || '-12.3')
  const ddColor = isDark ? '#f87171' : '#dc2626'

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const text = isDark ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)'
      const split = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
      return {
        backgroundColor: 'transparent',
        grid: { top: 20, right: 16, bottom: 12, left: 48 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => `回撤: <b>${Number(params[0].value).toFixed(2)}%</b>`,
        },
        xAxis: { type: 'category', data: data.map((d) => d.t), show: false },
        yAxis: {
          type: 'value',
          max: 0,
          min: -20,
          axisLabel: { color: text, fontSize: 10, formatter: '{value}%' },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
        },
        series: [{
          type: 'line',
          data: data.map((d) => d.dd),
          showSymbol: false,
          lineStyle: { color: ddColor, width: 1.5 },
          areaStyle: { color: ddColor, opacity: 0.1 },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ yAxis: maxDd }],
            lineStyle: { color: isDark ? 'rgba(248,113,113,0.4)' : 'rgba(220,38,38,0.4)', type: 'dashed' },
            label: {
              formatter: `Max DD ${maxDrawdown || '-12.3%'}`,
              color: isDark ? 'rgba(248,113,113,0.7)' : 'rgba(220,38,38,0.7)',
              fontSize: 10,
              position: 'insideEndTop',
            },
          },
        }],
      }
    },
    [data, isDark, maxDd, maxDrawdown, ddColor],
  )

  return <div ref={chartRef} className="w-full h-full" />
}

export function BacktestReturnsHistogram({ data }: { data: HistogramBin[] }) {
  return <ReturnsHistogramChart data={data} />
}
