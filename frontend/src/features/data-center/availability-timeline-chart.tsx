import React, { useState, useEffect, useCallback } from 'react'
import { Activity, Loader2, RefreshCw } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface TimelinePoint {
  time: string
  available: number
  error_rate: number
  calls: number
}

interface AvailabilityTimeline {
  source: string
  timeline: TimelinePoint[]
  summary: {
    total_hours: number
    available_hours: number
    availability_rate: number
  }
}

interface AvailabilityTimelineChartProps {
  source: string
  className?: string
}

export function AvailabilityTimelineChart({ source, className }: AvailabilityTimelineChartProps) {
  const [data, setData] = useState<AvailabilityTimeline | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchTimeline = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/datasource/${source}/availability-timeline`)
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
  }, [source])

  useEffect(() => {
    if (source) {
      fetchTimeline()
    }
  }, [source, fetchTimeline])

  const chartRef = useEChart(
    () => {
      if (!data || !data.timeline.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? ECHART_DARK.split : 'rgba(0,0,0,0.06)'

      return {
        backgroundColor: 'transparent',
        grid: { top: 40, right: 16, bottom: 32, left: 48 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : '#fff',
          borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#e2e8f0' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const time = params[0].axisValue
            const available = params[0]?.value
            const point = data.timeline.find((p) => p.time === time)

            const status = available === 1 ? '可用' : '不可用'
            const statusColor = available === 1 ? '#10b981' : '#ef4444'

            return `
              <div style="font-weight: 600;">${time}</div>
              <div style="margin-top: 4px;">
                状态：<span style="color: ${statusColor}; font-weight: 600;">${status}</span>
              </div>
              <div>
                调用次数：<span style="color: #3b82f6; font-weight: 600;">${point?.calls || 0}</span>
              </div>
              <div>
                错误率：<span style="color: #f59e0b; font-weight: 600;">${((point?.error_rate || 0) * 100).toFixed(2)}%</span>
              </div>
            `
          },
        },
        xAxis: {
          type: 'category',
          data: data.timeline.map((p) => p.time.split(' ')[1] || p.time),
          axisLabel: { color: text, fontSize: 9, rotate: 30 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: {
          type: 'value',
          name: '可用性',
          min: 0,
          max: 1,
          nameTextStyle: { color: text, fontSize: 9 },
          axisLabel: {
            color: text,
            fontSize: 9,
            formatter: (v: number) => (v === 1 ? '可用' : '不可用'),
          },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [
          {
            type: 'line',
            data: data.timeline.map((p) => p.available),
            lineStyle: {
              color: '#10b981',
              width: 3,
            },
            itemStyle: {
              color: (params: any) => (params.value === 1 ? '#10b981' : '#ef4444'),
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(16, 185, 129, 0.3)' },
                  { offset: 1, color: 'rgba(16, 185, 129, 0.05)' },
                ],
              },
            },
            symbol: 'circle',
            symbolSize: 8,
            smooth: false,
            step: 'end',
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
          <Activity className="h-4 w-4 text-emerald-400" />
          <h3 className="text-sm font-semibold text-foreground">可用性时间线</h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <button
          type="button"
          onClick={fetchTimeline}
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
      {data && data.summary.total_hours > 0 && (
        <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">总时长</div>
            <div className="text-sm font-semibold text-foreground">{data.summary.total_hours} 小时</div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">可用时长</div>
            <div className="text-sm font-semibold text-emerald-400">
              {data.summary.available_hours} 小时
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">可用率</div>
            <div className="text-sm font-semibold text-emerald-400">
              {(data.summary.availability_rate * 100).toFixed(2)}%
            </div>
          </div>
        </div>
      )}

      {/* 图表 */}
      {data && data.timeline.length > 0 ? (
        <div ref={chartRef} className="h-64 w-full" />
      ) : (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          {loading ? '加载中...' : '暂无可用性数据'}
        </div>
      )}

      {/* 数据源标识 */}
      {data && (
        <div className="mt-2 text-center text-[10px] text-muted-foreground">
          数据源：{data.source} · 过去 24 小时
        </div>
      )}
    </div>
  )
}
