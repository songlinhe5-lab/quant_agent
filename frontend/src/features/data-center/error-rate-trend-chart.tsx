import React, { useState, useEffect, useCallback } from 'react'
import { TrendingUp, Loader2, RefreshCw } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import { SEMANTIC_COLORS } from '@/lib/constants'

interface TimeSeriesPoint {
  time: string
  calls: number
  errors: number
  rate_limited: number
  error_rate: number
}

interface ErrorRateTrend {
  source: string
  time_series: TimeSeriesPoint[]
  summary: {
    total_calls: number
    total_errors: number
    total_rate_limited: number
    avg_error_rate: number
  }
}

interface ErrorRateTrendChartProps {
  source: string
  className?: string
}

export function ErrorRateTrendChart({ source, className }: ErrorRateTrendChartProps) {
  const [data, setData] = useState<ErrorRateTrend | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchTrend = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/datasource/${source}/error-rate-trend`)
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
      fetchTrend()
    }
  }, [source, fetchTrend])

  const chartRef = useEChart(
    () => {
      if (!data || !data.time_series.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? ECHART_DARK.split : 'rgba(0,0,0,0.06)'

      return {
        backgroundColor: 'transparent',
        grid: { top: 40, right: 60, bottom: 32, left: 48 },
        legend: {
          data: ['调用次数', '错误次数', '错误率'],
          top: 8,
          textStyle: { color: text, fontSize: 10 },
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : '#fff',
          borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#e2e8f0' : '#0f172a', fontSize: 11 },
          formatter: (params: any) => {
            const time = params[0].axisValue
            const calls = params[0]?.value || 0
            const errors = params[1]?.value || 0
            const errorRate = params[2]?.value || 0

            return `
              <div style="font-weight: 600;">${time}</div>
              <div style="margin-top: 4px;">
                调用：<span style="color: #3b82f6; font-weight: 600;">${calls}</span>
              </div>
              <div>
                错误：<span style="color: #ef4444; font-weight: 600;">${errors}</span>
              </div>
              <div>
                错误率：<span style="color: #f59e0b; font-weight: 600;">${(errorRate * 100).toFixed(2)}%</span>
              </div>
            `
          },
        },
        xAxis: {
          type: 'category',
          data: data.time_series.map((p) => p.time.split(' ')[1] || p.time),
          axisLabel: { color: text, fontSize: 9, rotate: 30 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: [
          {
            type: 'value',
            name: '次数',
            nameTextStyle: { color: text, fontSize: 9 },
            axisLabel: { color: text, fontSize: 9 },
            splitLine: { lineStyle: { color: split, type: 'dashed' } },
            axisLine: { show: false },
            axisTick: { show: false },
          },
          {
            type: 'value',
            name: '错误率',
            nameTextStyle: { color: text, fontSize: 9 },
            axisLabel: {
              color: text,
              fontSize: 9,
              formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
            },
            splitLine: { show: false },
            axisLine: { show: false },
            axisTick: { show: false },
          },
        ],
        series: [
          {
            name: '调用次数',
            type: 'bar',
            data: data.time_series.map((p) => p.calls),
            itemStyle: {
              color: SEMANTIC_COLORS.info,
              borderRadius: [4, 4, 0, 0],
            },
            barWidth: '40%',
          },
          {
            name: '错误次数',
            type: 'bar',
            data: data.time_series.map((p) => p.errors),
            itemStyle: {
              color: SEMANTIC_COLORS.bear,
              borderRadius: [4, 4, 0, 0],
            },
            barWidth: '40%',
          },
          {
            name: '错误率',
            type: 'line',
            yAxisIndex: 1,
            data: data.time_series.map((p) => p.error_rate),
            lineStyle: {
              color: SEMANTIC_COLORS.warn,
              width: 2,
            },
            itemStyle: {
              color: SEMANTIC_COLORS.warn,
            },
            symbol: 'circle',
            symbolSize: 6,
            smooth: true,
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
          <TrendingUp className="h-4 w-4 text-orange-400" />
          <h3 className="text-sm font-semibold text-foreground">错误率趋势</h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <button
          type="button"
          onClick={fetchTrend}
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
      {data && data.summary.total_calls > 0 && (
        <div className="mb-3 grid grid-cols-4 gap-2 text-xs">
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">总调用</div>
            <div className="text-sm font-semibold text-foreground">
              {data.summary.total_calls.toLocaleString()}
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">总错误</div>
            <div className="text-sm font-semibold text-red-400">
              {data.summary.total_errors.toLocaleString()}
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">限流次数</div>
            <div className="text-sm font-semibold text-orange-400">
              {data.summary.total_rate_limited.toLocaleString()}
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">平均错误率</div>
            <div className="text-sm font-semibold text-emerald-400">
              {(data.summary.avg_error_rate * 100).toFixed(2)}%
            </div>
          </div>
        </div>
      )}

      {/* 图表 */}
      {data && data.time_series.length > 0 ? (
        <div ref={chartRef} className="h-64 w-full" />
      ) : (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          {loading ? '加载中...' : '暂无错误率数据'}
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
