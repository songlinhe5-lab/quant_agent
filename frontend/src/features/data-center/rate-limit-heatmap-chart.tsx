import React, { useState, useEffect } from 'react'
import { Grid3x3, Loader2, RefreshCw } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface HeatmapPoint {
  source: string
  date: string
  rate_limited: number
  calls: number
  rate: number
}

interface RateLimitHeatmap {
  sources: string[]
  days: number
  heatmap: HeatmapPoint[]
}

interface RateLimitHeatmapChartProps {
  className?: string
}

export function RateLimitHeatmapChart({ className }: RateLimitHeatmapChartProps) {
  const [data, setData] = useState<RateLimitHeatmap | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchHeatmap = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get('/datasource/rate-limit-heatmap')
      if (res.data) {
        setData(res.data)
      } else {
        setError('获取失败')
        setData(null)
      }
    } catch (e: any) {
      setError(e.message || '网络请求失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchHeatmap()
  }, [])

  const chartRef = useEChart(
    () => {
      if (!data || !data.heatmap.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'

      // 准备热力图数据
      const dates = Array.from(new Set(data.heatmap.map((p) => p.date))).sort()
      const sources = data.sources

      const heatmapData = data.heatmap.map((p) => {
        const xIndex = dates.indexOf(p.date)
        const yIndex = sources.indexOf(p.source)
        return [xIndex, yIndex, p.rate]
      })

      return {
        backgroundColor: 'transparent',
        grid: { top: 40, right: 16, bottom: 60, left: 80 },
        tooltip: {
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : '#fff',
          borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#e2e8f0' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const [xIdx, yIdx, value] = params.data
            const date = dates[xIdx]
            const source = sources[yIdx]
            const point = data.heatmap.find((p) => p.date === date && p.source === source)

            return `
              <div style="font-weight: 600;">${source} - ${date}</div>
              <div style="margin-top: 4px;">
                限流次数：<span style="color: #ef4444; font-weight: 600;">${point?.rate_limited || 0}</span>
              </div>
              <div>
                总调用：<span style="color: #3b82f6; font-weight: 600;">${point?.calls || 0}</span>
              </div>
              <div>
                限流率：<span style="color: #f59e0b; font-weight: 600;">${((value as number) * 100).toFixed(2)}%</span>
              </div>
            `
          },
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLabel: { color: text, fontSize: 9, rotate: 45 },
          axisLine: { show: false },
          axisTick: { show: false },
          splitArea: { show: true },
        },
        yAxis: {
          type: 'category',
          data: sources,
          axisLabel: { color: text, fontSize: 10 },
          axisLine: { show: false },
          axisTick: { show: false },
          splitArea: { show: true },
        },
        visualMap: {
          min: 0,
          max: 0.2,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
          inRange: {
            color: isDark
              ? ['#1e293b', '#3b82f6', '#f59e0b', '#ef4444']
              : ['#f0f9ff', '#3b82f6', '#f59e0b', '#ef4444'],
          },
          textStyle: { color: text, fontSize: 10 },
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
        series: [
          {
            type: 'heatmap',
            data: heatmapData,
            label: {
              show: true,
              color: isDark ? '#e2e8f0' : '#0f172a',
              fontSize: 10,
              formatter: (params: any) => {
                const value = params.data[2]
                return `${(value * 100).toFixed(0)}%`
              },
            },
            emphasis: {
              itemStyle: {
                shadowBlur: 10,
                shadowColor: 'rgba(0, 0, 0, 0.5)',
              },
            },
          },
        ],
      }
    },
    [data, isDark],
  )

  return (
    <div className={cn('rounded-xl border border-border bg-card p-4 shadow-sm', className)}>
      {/* 头部 */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Grid3x3 className="h-4 w-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-foreground">限流热力图</h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <button
          type="button"
          onClick={fetchHeatmap}
          disabled={loading}
          className="flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* 统计信息 */}
      {data && data.heatmap.length > 0 && (
        <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">数据源数量</div>
            <div className="text-sm font-semibold text-foreground">{data.sources.length}</div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">统计天数</div>
            <div className="text-sm font-semibold text-foreground">{data.days} 天</div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">数据点</div>
            <div className="text-sm font-semibold text-foreground">{data.heatmap.length}</div>
          </div>
        </div>
      )}

      {/* 图表 */}
      {data && data.heatmap.length > 0 ? (
        <div ref={chartRef} className="h-80 w-full" />
      ) : (
        <div className="flex h-80 items-center justify-center text-sm text-muted-foreground">
          {loading ? '加载中...' : '暂无限流数据'}
        </div>
      )}

      {/* 数据源标识 */}
      {data && (
        <div className="mt-2 text-center text-[10px] text-muted-foreground">
          过去 {data.days} 天 · {data.sources.length} 个数据源
        </div>
      )}
    </div>
  )
}
