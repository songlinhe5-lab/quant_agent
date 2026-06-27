import React, { useState, useEffect } from 'react'
import { Search, Loader2, LineChart as LineChartIcon } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'

export function MacroChartPanel() {
  const [seriesId, setSeriesId] = useState('DGS10')
  const [inputValue, setInputValue] = useState('DGS10')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const fetchSeries = async (id: string) => {
    if (!id) return;
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/macro/series?series_id=${id}&limit=250`)
      if (res.data?.status === 'success' && res.data?.data) {
        const chartData = [...res.data.data].reverse().map(d => ({
          ...d,
          date: d.date.split(' ')[0]
        }))
        setData(chartData)
      } else {
        setError(res.data?.message || '获取失败')
        setData([])
      }
    } catch(e: any) {
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
    if (inputValue.trim()) {
      setSeriesId(inputValue.trim().toUpperCase())
    }
  }

  const quickTags = [
    { label: '10年美债 (DGS10)', id: 'DGS10' },
    { label: '核心CPI (CPILFESL)', id: 'CPILFESL' },
    { label: '非农就业 (PAYEMS)', id: 'PAYEMS' },
    { label: '失业率 (UNRATE)', id: 'UNRATE' },
    { label: '美联储资产 (WALCL)', id: 'WALCL' },
    { label: 'M2货币 (WM2NS)', id: 'WM2NS' }
  ]

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
           <button key={tag.id} onClick={() => { setInputValue(tag.id); setSeriesId(tag.id); }} className={cn("text-[9px] px-2 py-0.5 rounded-full border transition-colors", seriesId === tag.id ? "bg-indigo-500/15 border-indigo-500/30 text-indigo-600 dark:text-indigo-400 font-bold" : "bg-background border-border/50 text-muted-foreground hover:text-foreground")}>
             {tag.label}
           </button>
         ))}
      </div>

      <div className="flex-1 p-4 relative min-h-0 bg-slate-50/30 dark:bg-black/10">
         {error ? (<div className="flex items-center justify-center h-full text-xs text-red-500 font-mono bg-red-500/5 rounded-lg border border-red-500/10 p-4 text-center">⚠️ {error}</div>) : data.length > 0 ? (
           <ResponsiveContainer width="100%" height="100%">
             <LineChart data={data}>
               <XAxis dataKey="date" tick={{fontSize: 9, fill: isDark ? '#9ca3af' : '#64748b'}} tickMargin={8} minTickGap={40} axisLine={false} tickLine={false} />
               <YAxis domain={['auto', 'auto']} tick={{fontSize: 9, fill: isDark ? '#9ca3af' : '#64748b'}} tickMargin={8} axisLine={false} tickLine={false} width={40} />
               <Tooltip 
                 contentStyle={{ backgroundColor: isDark ? 'oklch(0.18 0.01 270)' : '#fff', border: isDark ? '1px solid rgba(139, 92, 246, 0.2)' : '1px solid rgba(0,0,0,0.1)', borderRadius: '8px', fontSize: '11px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                 itemStyle={{ color: isDark ? '#e2e8f0' : '#0f172a', fontWeight: 'bold' }}
                 labelStyle={{ color: isDark ? '#94a3b8' : '#64748b', marginBottom: '4px' }}
                 formatter={(val: any) => [val, seriesId]}
               />
               <Line type="monotone" dataKey="value" stroke="#8b5cf6" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: "#8b5cf6", stroke: isDark ? "#000" : "#fff", strokeWidth: 2 }} isAnimationActive={true} animationDuration={1000} />
             </LineChart>
           </ResponsiveContainer>
         ) : (<div className="flex items-center justify-center h-full text-xs text-muted-foreground">暂无数据</div>)}
      </div>
    </div>
  )
}