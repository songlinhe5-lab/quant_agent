import React, { useState, useEffect } from 'react'
import { BarChart3, Loader2, RefreshCw } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface LatencyBucket {
  range: string
  count: number
}

interface LatencyDistribution {
  source: string
  buckets: LatencyBucket[]
  total_samples: number
  avg_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
}

interface LatencyDistributionChartProps {
  source: string
  className?: string
}

export function LatencyDistributionChart({ source, className }: LatencyDistributionChartProps) {
  const [data, setData] = useState<LatencyDistribution | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchDistribution = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/datasource/${source}/latency-distribution`)
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
    if (source) {
      fetchDistribution()
    }
  }, [source])

  const chartRef = useEChart(
    () => {
      if (!data || !data.buckets.length) return null
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
            const param = params[0]
            return `
              <div style="font-weight: 600;">${param.name}</div>
              <div style="margin-top: 4px;">
                样本数：<span style="color: #8b5cf6; font-weight: 600;">${param.value}</span>
              </div>
              <div style="color: ${text}; font-size: 10px; margin-top: 2px;">
                占比：${((param.value / data.total_samples) * 100).toFixed(1)}%
              </div>
            `
          },
        },
        xAxis: {
          type: 'category',
          data: data.buckets.map((b) => b.range),
          axisLabel: { color: text, fontSize: 9, rotate: 30 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: text, fontSize: 9 },
          splitLine: { lineStyle: { color: split, type: 'dashed' } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [
          {
            type: 'bar',
            data: data.buckets.map((b) => b.count),
            itemStyle: {
              color: '#8b5cf6',
              borderRadius: [4, 4, 0, 0],
            },
            emphasis: {
              itemStyle: {
                color: '#a78bfa',
              },
            },
            barWidth: '60%',
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
          <BarChart3 className="h-4 w-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-foreground">延迟分布</h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <button
          type="button"
          onClick={fetchDistribution}
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
      {data && data.total_samples > 0 && (
        <div className="mb-3 grid grid-cols-4 gap-2 text-xs">
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">样本数</div>
            <div className="text-sm font-semibold text-foreground">{data.total_samples}</div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">平均延迟</div>
            <div className="text-sm font-semibold text-foreground">
              {data.avg_ms != null ? `${data.avg_ms.toFixed(0)} ms` : 'N/A'}
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">P50</div>
            <div className="text-sm font-semibold text-foreground">
              {data.p50_ms != null ? `${data.p50_ms.toFixed(0)} ms` : 'N/A'}
            </div>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground">P95</div>
            <div className="text-sm font-semibold text-emerald-400">
              {data.p95_ms != null ? `${data.p95_ms.toFixed(0)} ms` : 'N/A'}
            </div>
          </div>
        </div>
      )}

      {/* 图表 */}
      {data && data.buckets.length > 0 ? (
        <div ref={chartRef} className="h-64 w-full" />
      ) : (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          {loading ? '加载中...' : '暂无延迟数据'}
        </div>
      )}

      {/* 数据源标识 */}
      {data && (
        <div className="mt-2 text-center text-[10px] text-muted-foreground">
          数据源：{data.source} · Redis 持久化样本
        </div>
      )}
    </div>
  )
}
