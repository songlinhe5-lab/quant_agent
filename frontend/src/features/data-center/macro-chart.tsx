import React, { useState, useEffect } from 'react'
import { Search, Loader2, LineChart as LineChartIcon } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

export function MacroChartPanel() {
  const [seriesId, setSeriesId] = useState('DGS10')
  const [inputValue, setInputValue] = useState('DGS10')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchSeries = async (id: string) => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/macro/series?series_id=${id}&limit=250`)
      if (res.data?.status === 'success' && res.data?.data) {
        const chartData = [...res.data.data].reverse().map(d => ({
          ...d,
          date: d.date.split(' ')[0],
        }))
        setData(chartData)
      } else {
        setError(res.data?.message || '获取失败')
        setData([])
      }
    } catch (e: any) {
      setError(e.message || '网络请求失败')
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSeries(seriesId)
  }, [seriesId])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (inputValue.trim()) setSeriesId(inputValue.trim().toUpperCase())
  }

  const quickTags = [
    { label: '10年美债 (DGS10)', id: 'DGS10' },
    { label: '核心CPI (CPILFESL)', id: 'CPILFESL' },
    { label: '非农就业 (PAYEMS)', id: 'PAYEMS' },
    { label: '失业率 (UNRATE)', id: 'UNRATE' },
    { label: '美联储资产 (WALCL)', id: 'WALCL' },
    { label: 'M2货币 (WM2NS)', id: 'WM2NS' },
  ]

  const chartRef = useEChart(
    () => {
      if (!data.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? ECHART_DARK.split : 'rgba(0,0,0,0.06)'
      return {
        backgroundColor: 'transparent',
        grid: { top: 16, right: 16, bottom: 28, left: 48 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : '#fff',
          borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(0,0,0,0.1)',
          textStyle: { color: isDark ? '#e2e8f0' : '#0f172a', fontSize: 11 },
        },
        xAxis: {
          type: 'category',
          data: data.map((d) => d.date),
          axisLabel: { color: text, fontSize: 9 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLabel: { color: text, fontSize: 9 },
          splitLine: { lineStyle: { color: split } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [{
          name: seriesId,
          type: 'line',
          data: data.map((d) => d.value),
          showSymbol: false,
          lineStyle: { color: ECHART_DARK.primary, width: 2 },
          itemStyle: { color: ECHART_DARK.primary },
        }],
      }
    },
    [data, isDark, seriesId],
  )

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px]">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 flex-shrink-0">
        <LineChartIcon className="h-3.5 w-3.5 text-indigo-500 dark:text-indigo-400" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">FRED 宏观图表自由查</span>
        <form onSubmit={handleSearch} className="ml-auto flex items-center gap-1.5">
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 h-3 w-3 text-muted-foreground" />
            <input
              type="text"
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              placeholder="输入 FRED 序列 ID..."
              className="bg-secondary/30 border border-border/30 hover:bg-secondary/60 text-foreground text-[10px] rounded-full pl-7 pr-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary transition-colors w-40 font-mono uppercase"
            />
          </div>
          <button type="submit" disabled={loading} className="bg-indigo-500/15 border border-indigo-500/20 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/25 px-2.5 py-1 rounded-full text-[10px] font-bold transition-colors disabled:opacity-50 flex items-center gap-1">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <span>查询</span>}
          </button>
        </form>
      </div>

      <div className="px-4 py-2 bg-secondary/10 border-b border-border/20 flex flex-wrap gap-2">
        {quickTags.map(tag => (
          <button key={tag.id} onClick={() => { setInputValue(tag.id); setSeriesId(tag.id) }} className={cn('text-[9px] px-2 py-0.5 rounded-full border transition-colors', seriesId === tag.id ? 'bg-indigo-500/15 border-indigo-500/30 text-indigo-600 dark:text-indigo-400 font-bold' : 'bg-background border-border/50 text-muted-foreground hover:text-foreground')}>
            {tag.label}
          </button>
        ))}
      </div>

      <div className="flex-1 p-4 relative min-h-0 bg-slate-50/30 dark:bg-black/10">
        {error ? (
          <div className="flex items-center justify-center h-full text-xs text-red-500 font-mono bg-red-500/5 rounded-lg border border-red-500/10 p-4 text-center">⚠️ {error}</div>
        ) : data.length > 0 ? (
          <div ref={chartRef} className="w-full h-full" />
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-muted-foreground">暂无数据</div>
        )}
      </div>
    </div>
  )
}
