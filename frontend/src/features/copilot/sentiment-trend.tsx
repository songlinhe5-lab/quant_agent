'use client'

import { useState, useEffect } from 'react'
import { 
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, 
  ResponsiveContainer, ReferenceLine, ScatterChart, Scatter, ZAxis
} from 'recharts'
import { Activity, Loader2, Maximize2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'

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
      if (document.hidden) return; // 💡 性能优化：页面在后台时暂停网络请求
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
        console.error('Failed to fetch sentiment history', err)
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    fetchData()
    const timer = setInterval(fetchData, 60000 * 5) // 每 5 分钟刷新一次
    return () => { isMounted = false; clearInterval(timer) }
  }, [])

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      {/* 标题栏 */}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-violet-500 dark:text-violet-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            期权 P/C Ratio 趋势
          </span>
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
              "text-xs font-bold font-mono px-2 py-0.5 rounded",
              currentPC > 1.0 
                ? "bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]" 
                : "bg-[#0ecb81]/15 text-[#059669] dark:text-[#0ecb81]"
            )}>
              P/C: {currentPC.toFixed(2)}
            </span>
          )}
          <button className="text-muted-foreground hover:text-foreground transition-colors" title="全屏展开">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 图表主区域 */}
      <div className="flex-1 p-4">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: -20, left: -25, bottom: 0 }}>
            <defs>
              {/* P/C Ratio 专属渐变色，偏紫红色代表恐慌情绪 */}
              <linearGradient id="colorPc" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={isDark ? "#8b5cf6" : "#7c3aed"} stopOpacity={0.4}/>
                <stop offset="95%" stopColor={isDark ? "#8b5cf6" : "#7c3aed"} stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)"} />
            <XAxis 
              dataKey="time" 
              tick={{ fontSize: 9, fill: 'var(--muted-foreground)' }} 
              axisLine={false} 
              tickLine={false}
              minTickGap={30}
            />
            <YAxis 
              yAxisId="left"
              domain={['dataMin - 0.1', 'dataMax + 0.1']} 
              tick={{ fontSize: 9, fill: 'var(--muted-foreground)', fontFamily: 'monospace' }} 
              axisLine={false} 
              tickLine={false}
              tickFormatter={(val) => val.toFixed(2)}
            />
            <YAxis 
              yAxisId="right"
              orientation="right"
              domain={['dataMin - 2', 'dataMax + 2']} 
              tick={{ fontSize: 9, fill: 'var(--muted-foreground)', fontFamily: 'monospace' }} 
              axisLine={false} 
              tickLine={false}
              tickFormatter={(val) => val.toFixed(1)}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: isDark ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)', borderRadius: '8px', fontSize: '12px' }}
              itemStyle={{ fontWeight: 'bold' }}
              labelStyle={{ color: 'var(--muted-foreground)', marginBottom: '4px' }}
            />
            {/* 核心多空警戒分水岭 */}
            <ReferenceLine yAxisId="left" y={1.0} stroke={isDark ? "rgba(246,70,93,0.5)" : "rgba(225,29,72,0.5)"} strokeDasharray="3 3" label={{ position: 'insideTopLeft', value: '1.0 恐慌分水岭', fill: isDark ? '#f6465d' : '#e11d48', fontSize: 9 }} />
            
            <Area yAxisId="left" type="monotone" name="P/C Ratio" dataKey="pc_ratio" stroke={isDark ? "#8b5cf6" : "#7c3aed"} strokeWidth={2} fillOpacity={1} fill="url(#colorPc)" isAnimationActive={false} />
            <Line yAxisId="right" type="monotone" name="VIX 恐慌指数" dataKey="vix" stroke={isDark ? "#fbbf24" : "#f59e0b"} strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function VixCorrelationChart() {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  
  const [data, setData] = useState<any[]>([])

  useEffect(() => {
    // 使用 Mock 数据模拟标普500 (SPY) 与恐慌指数 (VIX) 的负相关性散点分布
    const mockData = Array.from({ length: 100 }, () => {
      const spyReturn = (Math.random() - 0.45) * 4; // SPY 日波动: -1.8% to +2.2%
      // VIX 通常带有显著的杠杆反向放大效应，以及随机波动噪音
      const vixReturn = -3.5 * spyReturn + (Math.random() - 0.5) * 8; 
      return { spy: parseFloat(spyReturn.toFixed(2)), vix: parseFloat(vixReturn.toFixed(2)) };
    });
    setData(mockData)
  }, [])

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      {/* 标题栏 */}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-blue-500 dark:text-blue-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            VIX vs SPY 宏观负相关性
          </span>
        </div>
      </div>

      {/* 图表主区域 */}
      <div className="flex-1 p-4">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 20, left: -20, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)"} />
            <XAxis 
              type="number" dataKey="spy" name="SPY 涨跌幅" unit="%" 
              tick={{ fontSize: 9, fill: 'var(--muted-foreground)' }} 
              axisLine={{ stroke: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)" }} tickLine={false}
            />
            <YAxis 
              type="number" dataKey="vix" name="VIX 涨跌幅" unit="%" 
              tick={{ fontSize: 9, fill: 'var(--muted-foreground)', fontFamily: 'monospace' }} 
              axisLine={{ stroke: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)" }} tickLine={false}
            />
            <ZAxis type="number" range={[20, 20]} />
            <Tooltip 
              cursor={{ strokeDasharray: '3 3' }} 
              contentStyle={{ backgroundColor: isDark ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)', borderRadius: '8px', fontSize: '11px' }}
              itemStyle={{ fontWeight: 'bold' }} labelStyle={{ display: 'none' }}
              formatter={(value: any, name: any) => [`${value > 0 ? '+' : ''}${value}%`, name === 'spy' ? 'SPY' : 'VIX']}
            />
            <ReferenceLine x={0} stroke={isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} />
            <ReferenceLine y={0} stroke={isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)"} />
            <Scatter name="Correlation" data={data} fill={isDark ? "#3b82f6" : "#2563eb"} fillOpacity={0.6} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}