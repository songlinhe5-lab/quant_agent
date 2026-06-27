import React, { useState, useEffect, useRef } from 'react'
import { Settings2, X, Loader2, BellRing, Power, Trash2, Database, Upload, Download, Plus, Search, LineChart } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { useTheme } from 'next-themes'
import { useConfirmDialog } from '@/components/confirm-dialog'
import { createChart, ColorType, CrosshairMode, CandlestickSeries, HistogramSeries } from 'lightweight-charts'
import { formatDisplaySymbol } from './shared'

// ── 订阅管理面板子组件 ──────────────────────────────────────────────────────
export function SubscriptionManagerPanel({ onClose }: { onClose: () => void }) {
  const [subs, setSubs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()

  useEffect(() => {
    const fetchSubs = async () => {
      try {
        const res = await apiClient.get('/screener/subscriptions')
        if (res.data?.status === 'success') setSubs(res.data.data)
      } catch (e) {
        console.error(e)
      } finally { setLoading(false) }
    }
    fetchSubs()
  }, [])

  const handleToggle = async (id: number) => {
    try {
      const res = await apiClient.put(`/screener/subscriptions/${id}/toggle`)
      if (res.data?.status === 'success') {
        setSubs(prev => prev.map(s => s.id === id ? { ...s, is_active: res.data.is_active } : s))
        toast({ title: '状态已更新', description: res.data.message })
      }
    } catch (e) {}
  }

  const handleDelete = async (id: number) => {
    const ok = await confirm({ title: '删除订阅任务', description: '确定要彻底删除该订阅任务吗？', confirmLabel: '删除' })
    if (!ok) return
    try {
      const res = await apiClient.delete(`/screener/subscriptions/${id}`)
      if (res.data?.status === 'success') {
        setSubs(prev => prev.filter(s => s.id !== id))
        toast({ title: '已删除', description: res.data.message })
      }
    } catch (e) {}
  }

  return (
    <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-2xl bg-card border border-border/40 rounded-xl overflow-hidden flex flex-col shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-secondary/20">
          <h3 className="text-sm font-bold flex items-center gap-2"><Settings2 className="h-4 w-4 text-violet-500 dark:text-violet-400" />管理订阅任务</h3>
          <button onClick={onClose} className="p-1 rounded-md hover:bg-secondary/50 text-muted-foreground hover:text-foreground transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar max-h-[60vh] min-h-[300px]">
          {loading ? (
            <div className="flex items-center justify-center h-full"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : subs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground space-y-2 py-10">
              <BellRing className="h-8 w-8 opacity-20" />
              <p className="text-xs">暂无订阅任务</p>
            </div>
          ) : (
            <div className="space-y-3">
              {subs.map(sub => (
                <div key={sub.id} className={cn("p-3 rounded-lg border flex flex-col gap-2 transition-colors duration-300", sub.is_active ? "bg-secondary/10 border-border/50" : "bg-secondary/5 border-border/20 opacity-60")}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={cn("h-2 w-2 rounded-full", sub.is_active ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" : "bg-muted-foreground/50")} />
                      <h4 className="text-xs font-bold text-foreground">{sub.name}</h4>
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => handleToggle(sub.id)} className={cn("px-2 py-1 rounded text-[10px] font-medium border flex items-center gap-1 transition-colors", sub.is_active ? "bg-amber-500/10 text-amber-600 dark:text-amber-500 border-amber-500/20 hover:bg-amber-500/20" : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-500 border-emerald-500/20 hover:bg-emerald-500/20")}>
                        <Power className="h-3 w-3" /> {sub.is_active ? '暂停推送' : '恢复推送'}
                      </button>
                      <button onClick={() => handleDelete(sub.id)} className="px-2 py-1 rounded text-[10px] font-medium border bg-red-500/10 text-red-600 dark:text-red-500 border-red-500/20 hover:bg-red-500/20 transition-colors flex items-center gap-1">
                        <Trash2 className="h-3 w-3" /> 删除
                      </button>
                    </div>
                  </div>
                  <code className="text-[10px] font-mono text-violet-600 dark:text-violet-400 bg-violet-500/5 p-2 rounded-md break-all block mt-1">
                    {sub.dsl}
                  </code>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── RAG 知识库管理面板组件 ──────────────────────────────────────────────────────
export function RagDictionaryPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [desc, setDesc] = useState('')
  const [rule, setRule] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()

  const fetchDict = async () => {
    try {
      const res = await apiClient.get('/screener/dictionary')
      if (res.data?.status === 'success') setItems(res.data.data)
    } catch (e) {} finally { setLoading(false) }
  }
  useEffect(() => { fetchDict() }, [])

  const handleAdd = async () => {
    if (!desc.trim() || !rule.trim()) return
    try {
      const res = await apiClient.post('/screener/dictionary', { desc, rule })
      if (res.data?.status === 'success') {
        toast({ title: '✅ 词库热更新成功', description: res.data.message })
        setDesc(''); setRule(''); fetchDict()
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '添加失败', description: e.message || '请求异常' })
    }
  }

  const handleDelete = async (d: string, r: string) => {
    const ok = await confirm({ title: '删除规则', description: '确定要删除这条规则吗？', confirmLabel: '删除' })
    if (!ok) return
    try {
      const res = await apiClient.delete('/screener/dictionary', { data: { desc: d, rule: r } })
      if (res.data?.status === 'success') {
        toast({ title: '🗑️ 删除成功', description: res.data.message })
        fetchDict()
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '删除失败', description: e.message || '请求异常' })
    }
  }

  const handleExportCSV = () => {
    if (items.length === 0) { toast({ title: '没有可导出的数据', variant: 'destructive' }); return }
    const headers = ['desc', 'rule']
    const csvRows = [headers.join(',')]
    items.forEach(item => {
      const d = `"${item.desc.replace(/"/g, '""')}"`
      const r = `"${item.rule.replace(/"/g, '""')}"`
      csvRows.push(`${d},${r}`)
    })
    const csvString = '\uFEFF' + csvRows.join('\n')
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `QuantEdge_RAG_Dictionary_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    toast({ title: '导出成功', description: `已为您导出 ${items.length} 条规则。` })
  }

  const handleImportCSV = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = async (ev) => {
      try {
        const text = ev.target?.result as string
        const lines = text.split('\n').filter(l => l.trim())
        if (lines.length < 2) throw new Error('CSV 文件内容为空或格式错误')
        
        const newItems = []
        for (let i = 1; i < lines.length; i++) {
          const line = lines[i].trim()
          if (!line) continue
          const match = line.match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g)
          if (match && match.length >= 2) {
            const d = match[0].replace(/^"|"$/g, '').replace(/""/g, '"').trim()
            const r = match.slice(1).join(',').replace(/^"|"$/g, '').replace(/""/g, '"').trim()
            if (d && r) newItems.push({ desc: d, rule: r })
          }
        }
        if (newItems.length === 0) throw new Error('没有解析到有效的规则记录')
        setLoading(true)
        const res = await apiClient.post('/screener/dictionary/batch', { items: newItems })
        if (res.data?.status === 'success') {
          toast({ title: '✅ 批量导入成功', description: res.data.message })
          fetchDict()
        }
      } catch (err: any) {
        toast({ variant: 'destructive', title: '导入失败', description: err.message || 'CSV解析异常' })
        setLoading(false)
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = ''
      }
    }
    reader.readAsText(file)
  }

  const filteredItems = items.filter(item => item.desc.toLowerCase().includes(searchQuery.toLowerCase()) || item.rule.toLowerCase().includes(searchQuery.toLowerCase()))

  return (
    <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-4xl max-h-[90vh] bg-card border border-border/40 rounded-xl overflow-hidden flex flex-col shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-secondary/20">
          <h3 className="text-sm font-bold flex items-center gap-2"><Database className="h-4 w-4 text-emerald-500 dark:text-emerald-400" />RAG 向量知识库 (黑话引擎)</h3>
          <div className="flex items-center gap-2">
            <input type="file" accept=".csv" className="hidden" ref={fileInputRef} onChange={handleImportCSV} />
            <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border bg-secondary/50 border-border/50 hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground">
              <Upload className="h-3 w-3" /> 导入
            </button>
            <button onClick={handleExportCSV} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border bg-secondary/50 border-border/50 hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground">
              <Download className="h-3 w-3" /> 导出
            </button>
            <div className="w-px h-3 bg-border/50 mx-1" />
            <button onClick={onClose} className="p-1 rounded-md hover:bg-secondary/50 text-muted-foreground hover:text-foreground transition-colors"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="p-4 border-b border-border/30 bg-secondary/10 flex flex-col gap-3 shrink-0">
          <p className="text-[10px] text-muted-foreground leading-relaxed"><strong className="text-foreground">极客模式：</strong> 添加自定义指标映射与选股组合，修改将触发 ChromaDB 重建向量索引，即刻在全局生效并教导 Agent。</p>
          <div className="flex gap-2 items-start">
            <div className="flex-1 flex flex-col gap-2">
              <input type="text" value={desc} onChange={e => setDesc(e.target.value)} placeholder="触发词汇/人类黑话 (例如: 神龙摆尾因子、高分红避险策略)" className="w-full bg-background border border-border/50 rounded-md px-3 py-1.5 text-xs outline-none focus:border-emerald-500/50" />
              <textarea value={rule} onChange={e => setRule(e.target.value)} placeholder="底层映射规则 (例如: - 神龙摆尾因子 -> 生成 filter: technical_patterns 加入 'rsi_oversold'...)" className="w-full bg-background border border-border/50 rounded-md px-3 py-1.5 text-xs outline-none focus:border-emerald-500/50 custom-scrollbar resize-none h-16" />
            </div>
            <Button onClick={handleAdd} disabled={!desc.trim() || !rule.trim()} className="h-[96px] bg-emerald-500 hover:bg-emerald-600 text-white shadow-sm flex-col gap-1 w-20">
              <Plus className="h-4 w-4" />
              <span className="text-[10px]">保存并<br />向量化</span>
            </Button>
          </div>
        </div>
        <div className="px-4 py-2 border-b border-border/30 bg-background flex items-center gap-2 shrink-0">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input type="text" placeholder="快捷搜索规则描述或内容..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full bg-transparent text-xs outline-none text-foreground placeholder:text-muted-foreground font-mono" />
          {searchQuery && <span className="text-[10px] text-muted-foreground shrink-0">找到 {filteredItems.length} 条</span>}
        </div>
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar min-h-[250px]">
          {loading ? (
            <div className="flex items-center justify-center h-full"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : filteredItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground space-y-2 py-10">
              <Database className="h-8 w-8 opacity-20" />
              <p className="text-xs">{searchQuery ? '无匹配规则' : '暂无自定义词条'}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredItems.map((item, i) => (
                <div key={i} className="p-3 rounded-lg border border-border/30 bg-secondary/5 flex flex-col gap-1.5 group transition-colors hover:bg-secondary/10 hover:border-border/50">
                  <div className="flex items-start justify-between gap-4">
                    <div className="text-xs font-bold text-emerald-600 dark:text-emerald-400 break-words flex-1 leading-relaxed">{item.desc}</div>
                    <button onClick={() => handleDelete(item.desc, item.rule)} className="opacity-0 group-hover:opacity-100 px-2 py-1 rounded text-[10px] font-medium border bg-red-500/10 text-red-600 dark:text-red-500 border-red-500/20 hover:bg-red-500/20 transition-all flex items-center gap-1 shrink-0"><Trash2 className="h-3 w-3" /> 移除</button>
                  </div>
                  <code className="text-[10px] font-mono text-muted-foreground bg-black/10 dark:bg-black/30 p-2 rounded border border-border/20 break-words whitespace-pre-wrap leading-relaxed">{item.rule}</code>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── K 线行情预览弹窗组件 ──────────────────────────────────────────────────────
export function ChartPreviewModal({ symbol, price, change, onClose }: { symbol: string, price?: number, change?: number, onClose: () => void }) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const { theme } = useTheme()

  useEffect(() => {
    let isMounted = true
    let chart: any = null

    const initChart = async () => {
      try {
        const res = await apiClient.get('/market/history', { params: { ticker: symbol, ktype: 'K_DAY', num: 100 } })
        if (!isMounted) return
        
        if (res.data?.status === 'success' && res.data.data) {
           if (chartContainerRef.current) {
             chart = createChart(chartContainerRef.current, {
               layout: {
                 background: { type: ColorType.Solid, color: 'transparent' },
                 textColor: theme === 'dark' ? '#94a3b8' : '#64748b',
               },
               grid: {
                 vertLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' },
                 horzLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' },
               },
               crosshair: { mode: CrosshairMode.Magnet },
               timeScale: { timeVisible: true, fixLeftEdge: true, fixRightEdge: true },
             })
             
             const candlestickSeries = chart.addSeries(CandlestickSeries, {
                upColor: theme === 'dark' ? '#10b981' : '#059669',
                downColor: theme === 'dark' ? '#ef4444' : '#dc2626',
                borderVisible: false,
                wickUpColor: theme === 'dark' ? '#10b981' : '#059669',
                wickDownColor: theme === 'dark' ? '#ef4444' : '#dc2626',
             })
             
             const volumeSeries = chart.addSeries(HistogramSeries, {
                color: '#26a69a',
                priceFormat: { type: 'volume' },
                priceScaleId: '',
             })
             
             chart.priceScale('').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

             const sortedData = [...res.data.data].sort((a, b) => new Date(a.time.replace(/-/g, '/')).getTime() - new Date(b.time.replace(/-/g, '/')).getTime())
             
             const candleData = sortedData.map((d: any) => ({
               time: new Date(d.time.replace(/-/g, '/')).getTime() / 1000,
               open: d.open, high: d.high, low: d.low, close: d.close
             }))
             
             const volData = sortedData.map((d: any) => ({
               time: new Date(d.time.replace(/-/g, '/')).getTime() / 1000,
               value: d.volume,
               color: d.close >= d.open ? (theme === 'dark' ? 'rgba(16, 185, 129, 0.5)' : 'rgba(5, 150, 105, 0.5)') : (theme === 'dark' ? 'rgba(239, 68, 68, 0.5)' : 'rgba(220, 38, 38, 0.5)')
             }))
             
             candlestickSeries.setData(candleData)
             volumeSeries.setData(volData)
             chart.timeScale().fitContent()
           }
        } else {
           setError(res.data?.message || '无法获取 K 线数据')
        }
      } catch (err: any) {
        if (isMounted) setError(err.message || '获取行情失败')
      } finally {
        if (isMounted) setLoading(false)
      }
    }
    
    initChart()
    
    const handleResize = () => {
      if (chart && chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight
        })
      }
    }
    
    window.addEventListener('resize', handleResize)
    
    return () => {
      isMounted = false
      window.removeEventListener('resize', handleResize)
      if (chart) chart.remove()
    }
  }, [symbol, theme])
  
  return (
    <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-3xl bg-card border border-border/40 rounded-xl overflow-hidden flex flex-col shadow-2xl h-[500px]" onClick={e => e.stopPropagation()}>
         <div className="flex items-center justify-between px-4 py-3 border-b border-border/30 bg-secondary/20">
           <div className="flex items-center gap-3">
             <h3 className="text-sm font-bold flex items-center gap-2"><LineChart className="h-4 w-4 text-primary" /> {formatDisplaySymbol(symbol)} 行情预览 (日线)</h3>
             {price !== undefined && change !== undefined && (
               <div className="flex items-center gap-2 ml-1">
                 <span className={cn("text-sm font-mono font-bold tabular-nums", change >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                   {Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                 </span>
                 <span className={cn("text-xs font-mono font-bold px-1.5 py-0.5 rounded-sm bg-background/50 border border-border/50", change >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                   {change >= 0 ? '+' : ''}{Number(change).toFixed(2)}%
                 </span>
               </div>
             )}
           </div>
           <button onClick={onClose} className="p-1 rounded-md hover:bg-secondary/50 text-muted-foreground hover:text-foreground transition-colors"><X className="h-4 w-4" /></button>
         </div>
         <div className="flex-1 relative bg-background/50">
           {loading && <div className="absolute inset-0 flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>}
           {error && <div className="absolute inset-0 flex items-center justify-center text-red-500 font-mono text-sm">{error}</div>}
           <div ref={chartContainerRef} className="w-full h-full" />
         </div>
      </div>
    </div>
  )
}