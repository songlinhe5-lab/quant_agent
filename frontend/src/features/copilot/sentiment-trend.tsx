'use client'

import { useState, useEffect } from 'react'
import { Activity, Loader2, Maximize2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import logger from '@/lib/logger'

export function PCRatioTrendChart() {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [currentPC, setCurrentPC] = useState<number | null>(null)
  const [currentVix, setCurrentVix] = useState<number | null>(null)

  useEffect(() => {
    let isMounted = true
    const fetchData = async () => {
      if (document.hidden) return
      try {
        setLoading(true)
        const res = await apiClient.get('/macro/sentiment-history?limit=150')
        if (res.data?.status === 'success' && isMounted) {
          const history = res.data.data
          setData(history)
          if (history.length > 0) {
            setCurrentPC(history[history.length - 1].pc_ratio)
            setCurrentVix(history[history.length - 1].vix)
          }
        }
      } catch (err) {
        logger.error('Failed to fetch sentiment history', err as Error)
      } finally {
        if (isMounted) setLoading(false)
      }
    }
    fetchData()
    const timer = setInterval(fetchData, 60000 * 5)
    return () => { isMounted = false; clearInterval(timer) }
  }, [])

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
      const purple = isDark ? '#8b5cf6' : '#7c3aed'
      return {
        backgroundColor: 'transparent',
        grid: { top: 24, right: 48, bottom: 24, left: 40 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { fontSize: 12 },
        },
        legend: { show: false },
        xAxis: {
          type: 'category',
          data: data.map((d) => d.time),
          axisLabel: { color: text, fontSize: 9 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: [
          {
            type: 'value',
            scale: true,
            axisLabel: { color: text, fontSize: 9, fontFamily: 'monospace', formatter: (v: number) => v.toFixed(2) },
            splitLine: { lineStyle: { color: split, type: 'dashed' } },
            axisLine: { show: false },
          },
          {
            type: 'value',
            scale: true,
            axisLabel: { color: text, fontSize: 9, fontFamily: 'monospace', formatter: (v: number) => v.toFixed(1) },
            splitLine: { show: false },
            axisLine: { show: false },
          },
        ],
        series: [
          {
            name: 'P/C Ratio',
            type: 'line',
            data: data.map((d) => d.pc_ratio),
            showSymbol: false,
            lineStyle: { color: purple, width: 2 },
            areaStyle: {
              color: {
                type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0.05, color: isDark ? 'rgba(139,92,246,0.4)' : 'rgba(124,58,237,0.4)' },
                  { offset: 0.95, color: 'rgba(139,92,246,0)' },
                ],
              },
            },
            markLine: {
              silent: true,
              symbol: 'none',
              data: [{ yAxis: 1.0 }],
              lineStyle: { color: isDark ? 'rgba(246,70,93,0.5)' : 'rgba(225,29,72,0.5)', type: 'dashed' },
              label: { formatter: '1.0 恐慌分水岭', color: isDark ? '#f6465d' : '#e11d48', fontSize: 9, position: 'insideStartTop' },
            },
          },
          {
            name: 'VIX 恐慌指数',
            type: 'line',
            yAxisIndex: 1,
            data: data.map((d) => d.vix),
            showSymbol: false,
            lineStyle: { color: isDark ? '#fbbf24' : '#f59e0b', width: 2 },
          },
        ],
      }
    },
    [data, isDark],
  )

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-violet-500 dark:text-violet-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">期权 P/C Ratio 趋势</span>
        </div>
        <div className="flex items-center gap-3">
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          {currentVix !== null && (
            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400">
              VIX: {currentVix.toFixed(2)}
            </span>
          )}
          {currentPC !== null && (
            <span className={cn(
              'text-xs font-bold font-mono px-2 py-0.5 rounded',
              currentPC > 1.0
                ? 'bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]'
                : 'bg-[#0ecb81]/15 text-[#059669] dark:text-[#0ecb81]',
            )}>
              P/C: {currentPC.toFixed(2)}
            </span>
          )}
          <button className="text-muted-foreground hover:text-foreground transition-colors" title="全屏展开">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="flex-1 p-4 min-h-0">
        <div ref={chartRef} className="w-full h-full" />
      </div>
    </div>
  )
}

export function VixCorrelationChart() {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const [data, setData] = useState<{ spy: number; vix: number }[]>([])

  useEffect(() => {
    const mockData = Array.from({ length: 100 }, () => {
      const spyReturn = (Math.random() - 0.45) * 4
      const vixReturn = -3.5 * spyReturn + (Math.random() - 0.5) * 8
      return { spy: parseFloat(spyReturn.toFixed(2)), vix: parseFloat(vixReturn.toFixed(2)) }
    })
    setData(mockData)
  }, [])

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
      const axis = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)'
      return {
        backgroundColor: 'transparent',
        grid: { top: 16, right: 24, bottom: 32, left: 40 },
        tooltip: {
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
          textStyle: { fontSize: 11 },
          formatter: (p: any) => {
            const [spy, vix] = p.data
            const fmt = (v: number) => `${v > 0 ? '+' : ''}${v}%`
            return `SPY: <b>${fmt(spy)}</b><br/>VIX: <b>${fmt(vix)}</b>`
          },
        },
        xAxis: {
          type: 'value',
          name: 'SPY %',
          nameTextStyle: { color: text, fontSize: 9 },
          axisLabel: { color: text, fontSize: 9 },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
          axisLine: { lineStyle: { color: axis } },
        },
        yAxis: {
          type: 'value',
          name: 'VIX %',
          nameTextStyle: { color: text, fontSize: 9 },
          axisLabel: { color: text, fontSize: 9, fontFamily: 'monospace' },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
          axisLine: { lineStyle: { color: axis } },
        },
        series: [{
          type: 'scatter',
          data: data.map((d) => [d.spy, d.vix]),
          symbolSize: 8,
          itemStyle: { color: isDark ? ECHART_DARK.accent : '#2563eb', opacity: 0.6 },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: axis },
            data: [{ xAxis: 0 }, { yAxis: 0 }],
          },
        }],
      }
    },
    [data, isDark],
  )

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-blue-500 dark:text-blue-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">VIX vs SPY 宏观负相关性</span>
        </div>
      </div>
      <div className="flex-1 p-4 min-h-0">
        <div ref={chartRef} className="w-full h-full" />
      </div>
    </div>
  )
}
