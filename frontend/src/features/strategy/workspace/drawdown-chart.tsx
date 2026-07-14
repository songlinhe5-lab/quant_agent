import { useRef, useEffect } from 'react'
import { useTheme } from 'next-themes'
import * as echarts from 'echarts'

/** ECharts underwater drawdown series with max-DD mark area/point. */
export function DrawdownChart({ drawdownStats }: { drawdownStats: any }) {
  const chartRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  const echartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current || !drawdownStats.data.length) return

    if (!echartInstance.current) {
      echartInstance.current = echarts.init(chartRef.current)
    }

    const isDark = theme === 'dark'
    const textColor = isDark ? '#94a3b8' : '#64748b'
    const splitLineColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
    const ddColor = isDark ? '#f87171' : '#dc2626'
    const areaColor = isDark ? 'rgba(248, 113, 113, 0.3)' : 'rgba(220, 38, 38, 0.3)'

    const dates = drawdownStats.data.map((d: any) => d.date)
    const values = drawdownStats.data.map((d: any) => d.dd)

    let markArea = {}
    let markPoint = {}
    if (drawdownStats.maxDdPeriod) {
      markArea = {
        silent: true,
        itemStyle: { color: 'rgba(245, 158, 11, 0.15)' },
        data: [[{ xAxis: drawdownStats.maxDdPeriod.start }, { xAxis: drawdownStats.maxDdPeriod.end }]],
      }
      markPoint = {
        data: [
          {
            name: '最大回撤',
            coord: [drawdownStats.maxDdPeriod.trough, drawdownStats.maxDdPeriod.maxDdValue],
            value: `${drawdownStats.maxDdPeriod.maxDdValue.toFixed(2)}%`,
            symbol: 'pin',
            symbolSize: 45,
            itemStyle: { color: ddColor },
            label: { color: '#fff', fontSize: 10 },
          },
        ],
      }
    }

    const option = {
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) =>
          `${params[0].name}<br/>回撤: <span style="color:${ddColor};font-weight:bold">${params[0].value.toFixed(2)}%</span>`,
        backgroundColor: isDark ? '#1e293b' : 'rgba(255, 255, 255, 0.95)',
        borderColor: splitLineColor,
        textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
      },
      grid: { top: 20, right: 30, bottom: 20, left: 50 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: splitLineColor } },
        axisLabel: { color: textColor, fontSize: 10 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        max: 0,
        splitLine: { lineStyle: { color: splitLineColor, type: 'dashed' } },
        axisLabel: { color: textColor, fontSize: 10, formatter: '{value}%' },
      },
      series: [
        {
          data: values,
          type: 'line',
          symbol: 'none',
          lineStyle: { color: ddColor, width: 1.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(220, 38, 38, 0)' },
              { offset: 1, color: areaColor },
            ]),
          },
          markArea,
          markPoint,
        },
      ],
    }

    echartInstance.current.setOption(option)
    const handleResize = () => echartInstance.current?.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawdownStats, theme])

  return <div ref={chartRef} className="w-full h-full" />
}
