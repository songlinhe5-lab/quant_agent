'use client'

import { useState, useEffect } from 'react'
import { Activity, Clock, Server, AlertTriangle, RefreshCw, Zap, Timer } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export function PerformancePanel() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const fetchLogs = async () => {
    try {
      setIsRefreshing(true)
      const res = await apiClient.get('/system/performance-logs?limit=100')
      if (res.data?.status === 'success') {
        setLogs(res.data.data)
      }
    } catch (e) {
      console.error('获取性能日志失败:', e)
    } finally {
      setLoading(false)
      setTimeout(() => setIsRefreshing(false), 500) // 保持旋转动画一小会儿
    }
  }

  useEffect(() => {
    fetchLogs()
    // 自动轮询：每分钟刷新一次
    const iv = setInterval(fetchLogs, 60000)
    return () => clearInterval(iv)
  }, [])

  return (
    <div className="space-y-4">
      {/* 标题控制栏 */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-slate-500 dark:bg-slate-400" />
        <h1 className="text-base font-bold tracking-tight">系统性能监控</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          System APM
        </span>
        
        <Button 
          variant="outline" 
          size="sm" 
          onClick={fetchLogs} 
          disabled={isRefreshing}
          className="ml-auto h-7 px-3 gap-1.5 text-[11px] bg-secondary/30 hover:bg-secondary/60 border-border/50"
        >
          <RefreshCw className={cn("h-3 w-3", isRefreshing && "animate-spin")} />
          {isRefreshing ? '同步中' : '刷新日志'}
        </Button>
      </div>

      {/* 核心日志表格卡片 */}
      <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm relative flex flex-col min-h-[500px] h-[calc(100vh-140px)]">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between bg-secondary/30 shrink-0">
          <div className="flex items-center gap-2">
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              性能异常追溯记录
              <span className="ml-2 bg-primary/10 text-primary px-1.5 py-0.5 rounded-md font-mono">{logs.length}</span>
            </span>
          </div>
        </div>

        <div className="overflow-auto flex-1 custom-scrollbar">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <tr className="border-b border-border/40">
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">时间 (Timestamp)</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">类型 (Type)</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium whitespace-nowrap">触发节点 (Endpoint)</th>
                <th className="px-4 py-3 text-right text-muted-foreground font-medium whitespace-nowrap">耗时/卡顿 (ms)</th>
                <th className="px-4 py-3 text-left text-muted-foreground font-medium">详情追溯 (Details)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/15">
              {loading ? (
                <tr><td colSpan={5} className="py-10 text-center text-muted-foreground"><RefreshCw className="h-5 w-5 animate-spin mx-auto mb-2 opacity-50" />加载中...</td></tr>
              ) : logs.length === 0 ? (
                <tr><td colSpan={5} className="py-10 text-center text-muted-foreground">🎉 当前系统极其健康，暂无任何慢请求或卡顿日志。</td></tr>
              ) : logs.map((log) => {
                const isBlock = log.log_type === 'event_loop_block'
                const typeColor = isBlock ? 'text-[#e11d48] dark:text-[#f6465d] bg-[#f6465d]/10 border-[#f6465d]/20' : 'text-amber-600 dark:text-amber-500 bg-amber-500/10 border-amber-500/20'
                const Icon = isBlock ? AlertTriangle : Timer

                return (
                  <tr key={log.id} className="hover:bg-muted/50 transition-colors group">
                    <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground whitespace-nowrap">{log.timestamp}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={cn("inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border", typeColor)}>
                        <Icon className="h-3 w-3" />
                        {isBlock ? '主循环阻塞 (Event Loop Block)' : '慢请求 (Slow Request)'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-foreground">{log.endpoint || '-'}</td>
                    <td className={cn("px-4 py-3 text-right font-mono font-bold tabular-nums", isBlock ? "text-[#e11d48] dark:text-[#f6465d]" : "text-amber-600 dark:text-amber-500")}>
                      {log.duration_ms.toFixed(1)} ms
                    </td>
                    <td className="px-4 py-3 text-[11px] text-muted-foreground leading-relaxed break-words max-w-md">
                      {log.details || '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}