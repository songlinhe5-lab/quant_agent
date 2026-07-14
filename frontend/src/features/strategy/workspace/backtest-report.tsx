import React, { useState, useMemo } from 'react'
import { LineChart as LineChartIcon, Loader2, Sparkles, Square, Play, BarChart3, Database, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { useStrategyStore } from '../stores'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { SandboxChart } from './sandbox-chart'
import { DrawdownChart } from './drawdown-chart'
import { ReturnsHistogramChart } from './returns-histogram-chart'
import { buildTearSheetMetrics, computeDrawdownStats, computeReturnsHistogram } from './backtest-report-stats'
import { LongestDrawdownsList, TradesTable, LimitOrdersTable } from './backtest-report-tables'
import {
  ReproducibilityBadgeView,
  extractReproducibilityBadge,
} from '@/features/backtest/reproducibility-badge'

export function BacktestReport() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const [selectedLimitOrderIdx, setSelectedLimitOrderIdx] = useState<number | null>(null)
  const [isSyncing, setIsSyncing] = useState(false)

  const handleSyncData = async () => {
    setIsSyncing(true)
    try {
      const res = await apiClient.post('/market/kline/sync', {
        ticker: store.testTicker,
        interval: '1d',
        force_full: false
      })
      if (res.data?.status === 'success') {
        toast({ title: '✅ 同步成功', description: res.data.message })
        store.setRuntimeError(null)
      } else {
        toast({ variant: 'destructive', title: '同步失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '同步异常', description: e.response?.data?.detail || e.message })
    } finally {
      setIsSyncing(false)
    }
  }

  const handleCancelBacktest = () => {
    store.setSimulating(false)
    toast({ variant: 'destructive', title: '🚨 回测已中止', description: '您手动取消了沙箱回测推演。' })
  }

  const handleCancelOptimize = () => {
    store.setOptimizing(false)
    toast({ variant: 'destructive', title: '🚨 寻优已中止', description: '您手动取消了参数空间寻优。' })
  }

  const handleLimitOrderClick = (order: any, idx: number) => {
    if (idx === -1) { setSelectedLimitOrderIdx(null); return; }
    setSelectedLimitOrderIdx(idx);
    const row = document.getElementById(`limit-order-row-${idx}`);
    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const applyOptimizedParams = async (className: string, params: any) => {
    let updatedCode = store.code;
    const currentSchema = store.formSchema.find((s: any) => s.class_name === className);
    if (currentSchema) {
      currentSchema.parameters.forEach((p: any) => {
        if (params[p.name] !== undefined) {
          let valStr = String(params[p.name]);
          if (p.type === 'str' || typeof params[p.name] === 'string') valStr = `'${params[p.name]}'`;
          else if (p.type === 'bool') valStr = params[p.name] ? 'True' : 'False';
          const regex = new RegExp(`((?<!\\.)\\b${p.name}\\b\\s*:\\s*[^=]+=\\s*)([^,\\)\\n]+)`, 'g');
          updatedCode = updatedCode.replace(regex, `$1${valStr}`);
        }
      });
    }

    if (updatedCode !== store.code) store.setCode(updatedCode);
    store.setFormSchema(store.formSchema.map((s: any) => s.class_name === className ? { ...s, parameters: s.parameters.map((p: any) => params[p.name] !== undefined ? { ...p, default: params[p.name] } : p) } : s));

    toast({ title: '🚀 启动沙箱推演', description: `正在挂载最优参数并执行推演...` })
    store.setSimulating(true); store.setBacktestResult(null); store.setRuntimeError(null);
    
    try {
      const res = await apiClient.post('/strategy/run-sandbox', {
        source_code: updatedCode, class_name: className, params: params, ticker: store.testTicker, period: store.backtestPeriod, initial_capital: parseFloat(store.initialCapital) || 100000, data_source: store.dataSource, debug_mode: store.isDebugMode, data_snapshot_id: store.dataSnapshotId || 'latest_published', random_seed: 42,
      })
      if (res.data?.status === 'success') {
        store.setBacktestResult(res.data.data)
        const m = res.data.data.metrics || res.data.data
        toast({ title: '✅ 回测推演完成', description: `夏普比率: ${m.sharpe_ratio} | 收益率: ${m.total_return}` })
      } else {
        toast({ variant: 'destructive', title: '沙箱崩溃', description: res.data?.message }); store.setRuntimeError(res.data?.message)
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '执行异常', description: e.message }); store.setRuntimeError(e.message)
    } finally { store.setSimulating(false) }
  }

  const metrics = store.backtestResult?.metrics || {}
  const tearSheetMetrics = store.backtestResult ? buildTearSheetMetrics(metrics) : []
  const reproBadge = extractReproducibilityBadge(store.backtestResult)

  const drawdownStats = useMemo(
    () => computeDrawdownStats(store.backtestResult?.equity_curve),
    [store.backtestResult],
  )

  const histogramData = useMemo(
    () => computeReturnsHistogram(store.backtestResult?.equity_curve),
    [store.backtestResult],
  )

  return (
    <div className="h-full w-full overflow-y-auto p-4 custom-scrollbar bg-slate-50 dark:bg-[oklch(0.09_0.005_270)] space-y-4">
      {store.runtimeError && (
        <div className="flex flex-col items-center justify-center p-8 border border-red-500/20 rounded-xl bg-red-500/5 shadow-inner mb-4 animate-in fade-in">
          <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mb-4">
            {store.runtimeError.includes("LOCAL_DATA_MISSING") ? <Database className="h-6 w-6 text-red-500" /> : <AlertTriangle className="h-6 w-6 text-red-500" />}
          </div>
          <h3 className="text-sm font-bold text-red-600 dark:text-red-400 mb-2">引擎执行中止</h3>
          <p className="text-xs text-red-500/80 mb-6 max-w-lg text-center leading-relaxed">
            {store.runtimeError.replace("LOCAL_DATA_MISSING:", "")}
          </p>
          {store.runtimeError.includes("LOCAL_DATA_MISSING") && (
            <Button 
              onClick={handleSyncData} 
              disabled={isSyncing}
              className="bg-indigo-500 hover:bg-indigo-600 text-white shadow-md transition-all h-9 text-xs px-6"
            >
              {isSyncing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Database className="mr-2 h-4 w-4" />}
              {isSyncing ? '正在从云端拉取并落库 (可能需要几分钟)...' : '一键同步本地 K 线数仓'}
            </Button>
          )}
        </div>
      )}

      {!store.isOptimizing && !store.optimizationResults && !store.isSimulating && !store.backtestResult && !store.runtimeError && (
        <div className="h-full flex flex-col items-center justify-center text-muted-foreground text-xs font-mono opacity-50 select-none">
          <Play className="h-10 w-10 mb-3 opacity-20" />
          请在右侧调整参数并点击「应用推演」或「智能寻优」
        </div>
      )}

      {store.isOptimizing && (
        <div className="flex flex-col items-center justify-center p-6 border border-border/40 rounded-xl bg-secondary/10 shadow-inner relative mb-4">
          <button onClick={handleCancelOptimize} className="absolute top-3 right-3 p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded transition-colors" title="中止寻优"><Square className="h-3 w-3 fill-current" /></button>
          <Loader2 className="h-6 w-6 animate-spin text-indigo-500 mb-2" />
          <span className="text-xs text-muted-foreground font-mono">正在遍历参数空间极速寻优中...</span>
        </div>
      )}
      
      {!store.isOptimizing && store.optimizationResults && store.optimizationResults.length > 0 && (
        <div className="glass-card rounded-xl p-4 border border-indigo-500/30 shadow-sm bg-indigo-500/5 animate-in fade-in slide-in-from-bottom-2 mb-4">
          <div className="flex items-center gap-2 mb-3"><Sparkles className="h-4 w-4 text-indigo-500" /><h3 className="text-xs font-bold text-indigo-600 dark:text-indigo-400">智能寻优 Top 3 (按夏普比率)</h3></div>
          <div className="space-y-2">
            {store.optimizationResults.slice(0, 3).map((res: any, idx: number) => (
              <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between p-2.5 rounded-lg bg-background/50 border border-border/50 gap-2 hover:border-indigo-500/50 transition-colors">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-bold text-muted-foreground w-4">#{idx + 1}</span>
                  {Object.entries(res.params).map(([k, v]) => (<span key={k} className="text-[10px] font-mono bg-secondary/50 px-1.5 py-0.5 rounded">{k}: <span className="text-foreground font-bold">{String(v)}</span></span>))}
                </div>
                <div className="flex items-center gap-3 text-[10px] font-mono shrink-0">
                  <span className="text-muted-foreground">夏普: <span className="text-emerald-500 font-bold">{res.metrics.sharpe_ratio}</span></span>
                  <span className="text-muted-foreground hidden xl:inline">收益: <span className="text-foreground font-bold">{res.metrics.total_return}</span></span>
                  <Button size="sm" variant="outline" className="h-6 px-2 text-[10px] ml-1 bg-background" onClick={() => applyOptimizedParams(store.optimizedClassName, res.params)}>一键应用</Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {store.isSimulating && !store.backtestResult && (
        <div className="glass-card rounded-xl p-4 border border-border/40 shadow-sm animate-in fade-in slide-in-from-bottom-2 mb-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-bold text-emerald-600/50 dark:text-emerald-400/50 flex items-center gap-1.5"><LineChartIcon className="h-4 w-4" /> 沙箱回测资金曲线 ({store.backtestPeriod.toUpperCase()})</h3>
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground font-mono">
              <button onClick={handleCancelBacktest} className="p-0.5 rounded bg-red-500/10 hover:bg-red-500/20 text-red-500 transition-colors" title="中止回测"><Square className="h-3 w-3 fill-current" /></button>
              <Loader2 className="h-3 w-3 animate-spin" /> 正在推演...
            </div>
          </div>
          <div className="w-full h-[220px] mt-2 rounded-lg bg-secondary/20 animate-pulse flex flex-col items-center justify-center border border-dashed border-border/30">
            <LineChartIcon className="h-8 w-8 text-muted-foreground/20 mb-2" />
            <span className="text-[10px] font-mono text-muted-foreground/40">引擎正在撮合历史 K 线与订单...</span>
          </div>
        </div>
      )}

      {store.backtestResult && store.backtestResult.equity_curve && (
      <div className={cn("animate-in fade-in slide-in-from-bottom-2 transition-opacity duration-300 mb-4 space-y-4 relative", store.isSimulating && "opacity-60 pointer-events-none")}>
        {/* STRAT-05: 轻量 loading 蒙层 */}
        {store.isSimulating && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/40 backdrop-blur-[1px] rounded-xl">
            <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-background/80 border border-border/50 shadow-sm">
              <Loader2 className="h-4 w-4 animate-spin text-emerald-500" />
              <span className="text-xs font-mono text-muted-foreground">正在以相同参数重跑沙箱...</span>
            </div>
          </div>
        )}
        <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm">
          <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between gap-2 flex-wrap bg-secondary/20">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-3.5 w-3.5 text-primary" />
              <span className="text-xs font-bold text-foreground uppercase tracking-wide">Tear Sheet 核心指标</span>
            </div>
            <ReproducibilityBadgeView badge={reproBadge} />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y divide-border/20">
            {tearSheetMetrics.map((m, i) => (
              <div key={i} className="px-4 py-3 bg-background/50 hover:bg-secondary/10 transition-colors">
                <p className="text-[10px] text-muted-foreground mb-1">{m.label}</p>
                <p className={cn(
                  'text-lg font-bold font-mono tabular-nums leading-tight',
                  m.dir > 0 ? 'text-emerald-600 dark:text-emerald-400' : m.dir < 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground'
                )}>{m.value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="glass-card rounded-xl border border-border/40 shadow-sm overflow-hidden flex flex-col">
          <Tabs defaultValue="equity">
            <div className="border-b border-border/30 px-3 bg-secondary/10">
              <TabsList className="bg-transparent p-0 gap-0 h-10">
                <TabsTrigger value="equity" className="text-[11px] px-4 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">净值曲线</TabsTrigger>
                <TabsTrigger value="drawdown" className="text-[11px] px-4 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">回撤分析</TabsTrigger>
                <TabsTrigger value="returns" className="text-[11px] px-4 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">收益分布</TabsTrigger>
                <TabsTrigger value="trades" className="text-[11px] px-4 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">交易流水</TabsTrigger>
                <TabsTrigger value="orders" className="text-[11px] px-4 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">限价挂单</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="equity" className="m-0 p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                  <LineChartIcon className="h-4 w-4" /> 沙箱回测资金曲线 ({store.backtestPeriod.toUpperCase()})
                  {store.isSimulating && <Loader2 className="h-3 w-3 animate-spin text-emerald-500 ml-2" />}
                </h3>
                <div className="flex gap-3 text-[10px] font-mono">
                  <span className="text-muted-foreground">引擎: <span className="text-violet-500 dark:text-violet-400 font-bold">{store.backtestResult.metrics?.engine || '🐢 Event-Driven'}</span></span>
                  <span className="text-emerald-500">收益: {store.backtestResult.metrics?.total_return}</span>
                </div>
              </div>
              <SandboxChart data={store.backtestResult.equity_curve} trades={store.backtestResult.trades} limitOrders={store.backtestResult.limit_orders} onLimitOrderClick={handleLimitOrderClick} selectedLimitOrderIdx={selectedLimitOrderIdx} />
            </TabsContent>
            <TabsContent value="drawdown" className="m-0 p-4">
              <div className="flex flex-col md:flex-row gap-4 h-auto md:h-[260px] mt-2">
                <div className="flex-1 border border-border/20 rounded-xl overflow-hidden bg-background/50 shadow-inner p-2">
                  <DrawdownChart drawdownStats={drawdownStats} />
                </div>
                <LongestDrawdownsList items={drawdownStats.longestDrawdowns || []} />
              </div>
            </TabsContent>
            <TabsContent value="returns" className="m-0 p-4">
              <div className="h-[260px] mt-2">
                <ReturnsHistogramChart data={histogramData} />
              </div>
            </TabsContent>
            <TabsContent value="trades" className="m-0">
              <TradesTable trades={store.backtestResult.trades || []} />
            </TabsContent>
            <TabsContent value="orders" className="m-0">
              <LimitOrdersTable
                orders={store.backtestResult.limit_orders || []}
                selectedIdx={selectedLimitOrderIdx}
                onSelect={handleLimitOrderClick}
              />
            </TabsContent>
          </Tabs>
        </div>
      </div>
      )}
    </div>
  )
}