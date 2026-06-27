import React, { useRef, useEffect, useState, useMemo } from 'react'
import { LineChart as LineChartIcon, Loader2, ListOrdered, Sparkles, Square, Play, BarChart3, TrendingDown, Database, AlertTriangle } from 'lucide-react'
import { createChart, ColorType, LineStyle, IChartApi, ISeriesApi, SeriesMarker, LineSeries, AreaSeries } from 'lightweight-charts'
import { useTheme } from 'next-themes'
import { cn } from '@/lib/utils'
import * as echarts from 'echarts'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Cell } from 'recharts'
import { Button } from '@/components/ui/button'
import { useStrategyStore } from '../stores/useStrategyStore'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

// ── SandboxChart (隔离渲染以保证性能) ──────────────────────────────────────
function SandboxChart({ 
  data, 
  trades = [],
  limitOrders = [],
  onLimitOrderClick,
  selectedLimitOrderIdx
}: { 
  data: any[], 
  trades?: any[],
  limitOrders?: any[],
  onLimitOrderClick?: (order: any, idx: number) => void,
  selectedLimitOrderIdx?: number | null
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const limitSeriesRefs = useRef<ISeriesApi<"Line">[]>([])
  const { theme } = useTheme()
  const onLimitOrderClickRef = useRef(onLimitOrderClick)

  useEffect(() => {
    onLimitOrderClickRef.current = onLimitOrderClick
  }, [onLimitOrderClick])
  
  useEffect(() => {
    if (!chartContainerRef.current || !data || data.length === 0) return

    const isDark = theme === 'dark'
    const textColor = isDark ? '#94a3b8' : '#64748b'
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: textColor,
      },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      rightPriceScale: { borderColor: gridColor },
      timeScale: { borderColor: gridColor, timeVisible: true, fixLeftEdge: true, fixRightEdge: true },
    })
    chartRef.current = chart

    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: '#8b5cf6', lineWidth: 2, lineStyle: LineStyle.Dashed, title: '基准(标的)',
    })
    benchmarkSeries.setData(data.map(d => ({ time: d.date, value: d.benchmark })))

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor: '#10b981', topColor: 'rgba(16, 185, 129, 0.3)', bottomColor: 'rgba(16, 185, 129, 0.01)', lineWidth: 2, title: '策略净值',
    })
    equitySeries.setData(data.map(d => ({ time: d.date, value: d.equity })))

    const priceSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.5)', lineWidth: 1, title: '标的价格', priceScaleId: 'price',
    })
    chart.priceScale('price').applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } })
    priceSeries.setData(data.map(d => ({ time: d.date, value: d.price || d.benchmark })))

    const globalMarkers: SeriesMarker<any>[] = []

    // 💡 注入历史买卖点信标 (Markers) 到价格曲线上
    if (trades && trades.length > 0) {
      trades.forEach((trade) => {
        let color = ''
        let shape: SeriesMarker<any>['shape'] = 'circle'
        let position: SeriesMarker<any>['position'] = 'inBar'
        let text = ''

        if (trade.action === 'BUY' || trade.action === 'COVER') {
          color = '#10b981' // emerald-500
          shape = 'arrowUp'
          position = 'belowBar'
          text = '买'
        } else if (trade.action === 'SELL' || trade.action === 'SHORT') {
          color = '#ef4444' // red-500
          shape = 'arrowDown'
          position = 'aboveBar'
          text = '卖'
        }

        if (color) {
          globalMarkers.push({ time: trade.date, position: position, color: color, shape: shape, text: text, size: 1 })
        }
      })
    }

    if (limitOrders && limitOrders.length > 0) {
      limitOrders.forEach(order => {
        const limitLine = chart.addSeries(LineSeries, {
          color: 'rgba(245, 158, 11, 0.8)', lineWidth: 2, lineStyle: LineStyle.Dotted, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceScaleId: 'price',
        })
        limitSeriesRefs.current.push(limitLine)
        limitLine.setData([{ time: order.start_date, value: order.price }, { time: order.end_date, value: order.price }])

        globalMarkers.push({ time: order.start_date, position: 'inBar', color: '#f59e0b', shape: 'circle', text: `🪝 挂单 @ ${order.price.toFixed(2)}` })

        let statusColor = '#64748b'
        let statusShape: SeriesMarker<any>['shape'] = 'circle'
        let statusText = '挂起中'

        if (order.status === 'FILLED') {
          statusColor = '#10b981'; statusShape = 'arrowUp'; statusText = '⚡ 成交'
        } else if (order.status === 'CANCELED') {
          statusColor = '#ef4444'; statusShape = 'arrowDown'; statusText = '❌ 撤单'
        }
        globalMarkers.push({ time: order.end_date, position: order.status === 'FILLED' ? 'belowBar' : 'aboveBar', color: statusColor, shape: statusShape, text: statusText })
      })
    }

    if (globalMarkers.length > 0) {
      globalMarkers.sort((a, b) => new Date(a.time as string).getTime() - new Date(b.time as string).getTime())
      ;(priceSeries as any).setMarkers(globalMarkers)
    }

    chart.subscribeClick((param) => {
      if (!param.point) return;
      const point = param.point;
      let closestIdx = -1; let minDistance = Infinity;

      limitOrders.forEach((order, idx) => {
        const series = limitSeriesRefs.current[idx];
        if (!series) return;
        const y = series.priceToCoordinate(order.price);
        const x1 = chart.timeScale().timeToCoordinate(order.start_date);
        const x2 = chart.timeScale().timeToCoordinate(order.end_date);
        if (y !== null && x1 !== null && x2 !== null) {
          const minX = Math.min(x1 as number, x2 as number);
          const maxX = Math.max(x1 as number, x2 as number);
          if (point.x >= minX - 15 && point.x <= maxX + 15) {
            const dist = Math.abs(point.y - y);
            if (dist < 15 && dist < minDistance) { minDistance = dist; closestIdx = idx; }
          }
        }
      });
      if (onLimitOrderClickRef.current) onLimitOrderClickRef.current(closestIdx !== -1 ? limitOrders[closestIdx] : null, closestIdx);
    });

    chart.timeScale().fitContent()
    const handleResize = () => { if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth }) }
    window.addEventListener('resize', handleResize)

    return () => { window.removeEventListener('resize', handleResize); chart.remove(); limitSeriesRefs.current = [] }
  }, [data, limitOrders, theme])

  useEffect(() => {
    limitSeriesRefs.current.forEach((series, idx) => {
      series.applyOptions({
        color: selectedLimitOrderIdx === idx ? 'rgba(245, 158, 11, 1)' : 'rgba(245, 158, 11, 0.8)',
        lineWidth: selectedLimitOrderIdx === idx ? 3 : 2,
      })
    })
  }, [selectedLimitOrderIdx])
  
  return <div ref={chartContainerRef} className="w-full h-[260px] mt-2 rounded-xl overflow-hidden border border-border/20 shadow-inner" />
}

// ── ECharts 水下回撤分析组件 ────────────────────────────────────────────────
function DrawdownChart({ drawdownStats }: { drawdownStats: any }) {
  const chartRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  const echartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current || !drawdownStats.data.length) return
    
    if (!echartInstance.current) {
      echartInstance.current = echarts.init(chartRef.current)
    }
    
    const isDark = theme === 'dark'
    const textColor = isDark ? '#94a3b8' : '#64748b'
    const splitLineColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
    const ddColor = isDark ? '#f87171' : '#dc2626'
    const areaColor = isDark ? 'rgba(248, 113, 113, 0.3)' : 'rgba(220, 38, 38, 0.3)'

    const dates = drawdownStats.data.map((d: any) => d.date)
    const values = drawdownStats.data.map((d: any) => d.dd)
    
    // 构造最大回撤标域 (MarkArea) 和最低点大头针 (MarkPoint)
    let markArea = {}; let markPoint = {};
    if (drawdownStats.maxDdPeriod) {
      markArea = {
        silent: true,
        itemStyle: { color: isDark ? 'rgba(245, 158, 11, 0.15)' : 'rgba(245, 158, 11, 0.15)' },
        data: [ [ { xAxis: drawdownStats.maxDdPeriod.start }, { xAxis: drawdownStats.maxDdPeriod.end } ] ]
      }
      markPoint = {
        data: [
          {
            name: '最大回撤',
            coord: [drawdownStats.maxDdPeriod.trough, drawdownStats.maxDdPeriod.maxDdValue],
            value: `${drawdownStats.maxDdPeriod.maxDdValue.toFixed(2)}%`,
            symbol: 'pin',
            symbolSize: 45,
            itemStyle: { color: ddColor },
            label: { color: '#fff', fontSize: 10 }
          }
        ]
      }
    }

    const option = {
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => `${params[0].name}<br/>回撤: <span style="color:${ddColor};font-weight:bold">${params[0].value.toFixed(2)}%</span>`,
        backgroundColor: isDark ? '#1e293b' : 'rgba(255, 255, 255, 0.95)',
        borderColor: splitLineColor,
        textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 }
      },
      grid: { top: 20, right: 30, bottom: 20, left: 50 },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: splitLineColor } }, axisLabel: { color: textColor, fontSize: 10 }, axisTick: { show: false } },
      yAxis: { type: 'value', max: 0, splitLine: { lineStyle: { color: splitLineColor, type: 'dashed' } }, axisLabel: { color: textColor, fontSize: 10, formatter: '{value}%' } },
      series: [
        {
          data: values, type: 'line', symbol: 'none', lineStyle: { color: ddColor, width: 1.5 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [ { offset: 0, color: 'rgba(220, 38, 38, 0)' }, { offset: 1, color: areaColor } ]) },
          markArea: markArea,
          markPoint: markPoint
        }
      ]
    }

    echartInstance.current.setOption(option)
    const handleResize = () => echartInstance.current?.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawdownStats, theme])

  return <div ref={chartRef} className="w-full h-full" />
}

// ── 回测报表主组件 ────────────────────────────────────────────────────────
export function BacktestReport() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const { theme } = useTheme()
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
        source_code: updatedCode, class_name: className, params: params, ticker: store.testTicker, period: store.backtestPeriod, initial_capital: parseFloat(store.initialCapital) || 100000, data_source: store.dataSource, debug_mode: store.isDebugMode
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
  const tearSheetMetrics = store.backtestResult ? [
    { label: '总收益率',   value: metrics.total_return || '--',  dir: parseFloat(metrics.total_return) > 0 ? 1 : -1 },
    { label: '年化收益率', value: metrics.annualized_return || '--',  dir: parseFloat(metrics.annualized_return) > 0 ? 1 : -1 },
    { label: '夏普比率',   value: metrics.sharpe_ratio || '--',   dir: parseFloat(metrics.sharpe_ratio) > 1 ? 1 : -1 },
    { label: '最大回撤',   value: metrics.max_drawdown || '--', dir: -1 },
    { label: '胜率',       value: metrics.win_rate || '--',  dir: parseFloat(metrics.win_rate) > 50 ? 1 : -1 },
    { label: '盈亏比',     value: metrics.profit_factor || '--',   dir: parseFloat(metrics.profit_factor) > 1 ? 1 : -1 },
    { label: '总交易次数', value: String(metrics.total_trades || '--'),  dir: 0 },
    { label: '摩擦成本',   value: metrics.total_friction_cost || '--', dir: -1 },
  ] : []

  const drawdownStats = useMemo(() => {
    if (!store.backtestResult?.equity_curve) return { data: [], maxDdPeriod: null, longestDrawdowns: [] };
    let maxEq = 0;
    let currentPeakDate = '';
    let maxDd = 0;
    let maxDdPeakDate = '';
    let maxDdTroughDate = '';
    
    // 新增：追踪所有破窗回撤期状态机
    const allDrawdowns: any[] = [];
    let inDrawdown = false;
    let currentDdStart = '';
    let currentDdTrough = '';
    let currentDdMaxDepth = 0;

    const data = store.backtestResult.equity_curve.map((d: any) => {
      if (d.equity > maxEq) { maxEq = d.equity; currentPeakDate = d.date; }
      const dd = maxEq > 0 ? ((maxEq - d.equity) / maxEq) * 100 : 0;
      if (dd > maxDd) { maxDd = dd; maxDdPeakDate = currentPeakDate; maxDdTroughDate = d.date; }
      
      // 水下状态机：记录每一次发生回撤的区间
      if (d.equity < maxEq) {
        if (!inDrawdown) {
          inDrawdown = true;
          currentDdStart = currentPeakDate;
          currentDdMaxDepth = dd;
          currentDdTrough = d.date;
        } else {
          if (dd > currentDdMaxDepth) {
            currentDdMaxDepth = dd;
            currentDdTrough = d.date;
          }
        }
      } else if (d.equity >= maxEq && inDrawdown) {
        // 资金创新高，成功修复回撤
        const startDate = new Date(currentDdStart);
        const endDate = new Date(d.date);
        const durationDays = Math.floor((endDate.getTime() - startDate.getTime()) / (1000 * 3600 * 24));
        
        if (durationDays > 0) {
          allDrawdowns.push({ start: currentDdStart, trough: currentDdTrough, end: d.date, depth: currentDdMaxDepth, duration: durationDays, recovered: true });
        }
        inDrawdown = false;
        currentDdMaxDepth = 0;
      }
      
      return { date: d.date, dd: -dd };
    });
    
    // 处理回测结束时仍在水下（未修复）的情况
    if (inDrawdown && data.length > 0) {
      const lastDate = store.backtestResult.equity_curve[store.backtestResult.equity_curve.length - 1].date;
      const startDate = new Date(currentDdStart);
      const endDate = new Date(lastDate);
      const durationDays = Math.floor((endDate.getTime() - startDate.getTime()) / (1000 * 3600 * 24));
      if (durationDays > 0) {
        allDrawdowns.push({ start: currentDdStart, trough: currentDdTrough, end: lastDate, depth: currentDdMaxDepth, duration: durationDays, recovered: false });
      }
    }

    // 按回撤经历的总天数降序，提取前 5 大最痛苦煎熬期
    const longestDrawdowns = [...allDrawdowns].sort((a, b) => b.duration - a.duration).slice(0, 5);

    // 计算回撤修复日 (Recovery Date)
    let recoveryDate = '';
    const peakEq = store.backtestResult.equity_curve.find((d: any) => d.date === maxDdPeakDate)?.equity || 0;
    if (peakEq > 0 && maxDdTroughDate) {
       let pastTrough = false;
       for (const d of store.backtestResult.equity_curve) {
          if (d.date === maxDdTroughDate) pastTrough = true;
          if (pastTrough && d.date !== maxDdTroughDate && d.equity >= peakEq) {
             recoveryDate = d.date; break;
          }
       }
    }
    
    return { 
      data, 
      maxDdPeriod: maxDd > 0 ? { start: maxDdPeakDate, trough: maxDdTroughDate, end: recoveryDate || data[data.length-1].date, maxDdValue: -maxDd } : null,
      longestDrawdowns
    };
  }, [store.backtestResult])

  const histogramData = useMemo(() => {
    const defaultData = [
       { range: '< -5%',  count: 0, color: '#f87171', lightColor: '#dc2626' },
       { range: '-5~-3%', count: 0, color: '#fca5a5', lightColor: '#ef4444' },
       { range: '-3~-1%', count: 0, color: '#fcd34d', lightColor: '#f59e0b' },
       { range: '-1~0%',  count: 0, color: '#d1d5db', lightColor: '#9ca3af' },
       { range: '0~1%',   count: 0, color: '#6ee7b7', lightColor: '#10b981' },
       { range: '1~3%',   count: 0, color: '#34d399', lightColor: '#059669' },
       { range: '3~5%',   count: 0, color: '#10b981', lightColor: '#047857' },
       { range: '> 5%',   count: 0, color: '#059669', lightColor: '#064e3b' },
    ];

    const eqCurve = store.backtestResult?.equity_curve;
    if (!eqCurve || eqCurve.length < 2) return defaultData;

    const counts = [0, 0, 0, 0, 0, 0, 0, 0];
    const totalDays = eqCurve.length - 1;
    
    for (let i = 1; i < eqCurve.length; i++) {
      const prevEq = eqCurve[i - 1].equity;
      const currEq = eqCurve[i].equity;
      if (prevEq > 0) {
        const retPct = ((currEq - prevEq) / prevEq) * 100;
        if (retPct < -5) counts[0]++;
        else if (retPct < -3) counts[1]++;
        else if (retPct < -1) counts[2]++;
        else if (retPct < 0) counts[3]++;
        else if (retPct < 1) counts[4]++;
        else if (retPct < 3) counts[5]++;
        else if (retPct < 5) counts[6]++;
        else counts[7]++;
      }
    }
    return defaultData.map((item, idx) => ({ 
      ...item, 
      count: counts[idx],
      percent: totalDays > 0 ? ((counts[idx] / totalDays) * 100).toFixed(1) : '0.0'
    }));
  }, [store.backtestResult])

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
      <div className={cn("animate-in fade-in slide-in-from-bottom-2 transition-opacity duration-300 mb-4 space-y-4", store.isSimulating && "opacity-60 pointer-events-none")}>
        <div className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm">
          <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 bg-secondary/20">
            <BarChart3 className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-bold text-foreground uppercase tracking-wide">Tear Sheet 核心指标</span>
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
                <div className="w-full md:w-64 border border-border/20 rounded-xl bg-background/50 shadow-inner p-3 flex flex-col overflow-hidden shrink-0">
                  <h4 className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5 shrink-0">
                    <TrendingDown className="h-3.5 w-3.5" /> 最长回撤期 Top 5
                  </h4>
                  <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-1">
                    {drawdownStats.longestDrawdowns && drawdownStats.longestDrawdowns.length > 0 ? (
                      drawdownStats.longestDrawdowns.map((dd: any, idx: number, arr: any[]) => {
                        // 💡 计算该次回撤的相对深度，用于渲染进度条
                        const maxD = Math.max(...arr.map((d) => d.depth));
                        const depthPct = maxD > 0 ? (dd.depth / maxD) * 100 : 0;
                        return (
                          <div key={idx} className="bg-secondary/20 p-2 rounded-lg border border-border/30 text-[10px] hover:border-red-500/30 transition-colors">
                            <div className="flex justify-between items-center mb-1.5">
                              <span className="font-bold text-foreground flex items-center gap-1"><span className="text-muted-foreground">#{idx + 1}</span> 经历 {dd.duration} 天</span>
                              <span className="text-red-500 font-mono font-bold">-{dd.depth.toFixed(2)}%</span>
                            </div>
                            {/* 💡 深度相对比例条 (类似伤害条) */}
                            <div className="w-full h-1 bg-border/50 rounded-full mb-1.5 overflow-hidden">
                              <div className="h-full bg-red-500/60 rounded-full" style={{ width: `${depthPct}%` }} />
                            </div>
                            <div className="text-muted-foreground flex justify-between font-mono text-[9px]">
                              <span>{dd.start}</span><span className="mx-1">→</span>
                              {dd.recovered ? <span>{dd.end}</span> : <span className="text-red-500 font-bold flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse"></span>至今未修复</span>}
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-center text-[10px] text-muted-foreground mt-10">暂无回撤记录</div>
                    )}
                  </div>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="returns" className="m-0 p-4">
              <div className="h-[260px] mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={histogramData} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={theme === 'dark' ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)"} />
                    <XAxis dataKey="range" tick={{ fill: theme === 'dark' ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)', fontSize: 9 }} />
                    <YAxis tick={{ fill: theme === 'dark' ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)', fontSize: 10 }} />
                    <RechartsTooltip
                      contentStyle={{ background: theme === 'dark' ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', border: theme === 'dark' ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)', borderRadius: '6px', fontSize: 11 }}
                      formatter={(v: any, name: any, props: any) => [`${v} 天 (占 ${props.payload.percent}%)`, '发生频次']}
                      cursor={{ fill: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}
                    />
                    <Bar dataKey="count" radius={[2, 2, 0, 0]} isAnimationActive={true}>
                      {histogramData.map((d, i) => <Cell key={i} fill={theme === 'dark' ? d.color : d.lightColor} fillOpacity={0.8} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>
            <TabsContent value="trades" className="m-0">
              {store.backtestResult.trades && store.backtestResult.trades.length > 0 ? (
                <div className="overflow-x-auto custom-scrollbar max-h-64">
                  <table className="w-full text-xs text-left"><thead className="bg-slate-50/50 dark:bg-black/20 text-muted-foreground sticky top-0 z-10"><tr><th className="px-4 py-2 font-medium">日期</th><th className="px-4 py-2 font-medium">方向</th><th className="px-4 py-2 font-medium text-right">成交价</th><th className="px-4 py-2 font-medium text-right">股数</th><th className="px-4 py-2 font-medium text-right">平仓盈亏</th></tr></thead>
                    <tbody className="divide-y divide-border/20">
                      {store.backtestResult.trades.map((trade: any, idx: number, arr: any[]) => {
                        // 💡 动态推断持仓天数
                        let holdingDays = '';
                        if (['SELL', 'COVER'].includes(trade.action)) {
                          for (let i = idx - 1; i >= 0; i--) {
                            if (['BUY', 'SHORT'].includes(arr[i].action)) {
                              const start = new Date(arr[i].date).getTime();
                              const end = new Date(trade.date).getTime();
                              const days = Math.max(1, Math.round((end - start) / (1000 * 3600 * 24)));
                              holdingDays = `历时 ${days} 天`;
                              break;
                            }
                          }
                        }
                        return (
                          <tr key={idx} className="hover:bg-secondary/20 transition-colors"><td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground flex items-center">{trade.date} {holdingDays && <span className="ml-2 text-[9px] text-indigo-400 bg-indigo-500/10 px-1 py-0.5 rounded">{holdingDays}</span>}</td><td className="px-4 py-2.5 font-bold text-[10px]"><span className={cn("px-1.5 py-0.5 rounded", ['BUY', 'COVER'].includes(trade.action) ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400')}>{trade.action}</span></td><td className="px-4 py-2.5 text-right font-mono text-[11px]">${Number(trade.price).toFixed(2)}</td><td className="px-4 py-2.5 text-right font-mono text-[11px] text-muted-foreground">{trade.shares}</td><td className={cn("px-4 py-2.5 text-right font-mono text-[11px] font-bold", trade.profit > 0 ? "text-emerald-500" : trade.profit < 0 ? "text-red-500" : "text-muted-foreground")}>{['SELL', 'COVER'].includes(trade.action) ? (trade.profit > 0 ? `+$${Number(trade.profit).toFixed(2)}` : `-$${Math.abs(Number(trade.profit)).toFixed(2)}`) : '-'}</td></tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : <div className="p-8 text-center text-muted-foreground text-xs">无交易记录</div>}
            </TabsContent>
            <TabsContent value="orders" className="m-0">
              {store.backtestResult.limit_orders && store.backtestResult.limit_orders.length > 0 ? (
                <div className="overflow-x-auto custom-scrollbar max-h-64">
                  <table className="w-full text-xs text-left whitespace-nowrap"><thead className="bg-slate-50/50 dark:bg-black/20 text-muted-foreground sticky top-0 z-10"><tr><th className="px-4 py-2 font-medium">挂单日</th><th className="px-4 py-2 font-medium">终结日</th><th className="px-4 py-2 font-medium text-right">限价 (Limit)</th><th className="px-4 py-2 font-medium text-center">最终状态</th></tr></thead>
                    <tbody className="divide-y divide-border/20">
                      {store.backtestResult.limit_orders.map((order: any, idx: number) => (<tr key={idx} id={`limit-order-row-${idx}`} className={cn("transition-colors cursor-pointer", selectedLimitOrderIdx === idx ? "bg-amber-500/20" : "hover:bg-secondary/20")} onClick={() => handleLimitOrderClick(order, idx)}><td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">{order.start_date}</td><td className="px-4 py-2.5 font-mono text-[10px] text-muted-foreground">{order.end_date}</td><td className="px-4 py-2.5 text-right font-mono text-[11px] font-bold text-amber-500">${Number(order.price).toFixed(2)}</td><td className="px-4 py-2.5 text-center"><span className={cn("px-2 py-0.5 rounded text-[10px] font-bold border", order.status === 'FILLED' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30' : order.status === 'CANCELED' ? 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30' : 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30')}>{order.status === 'FILLED' ? '✅ 成交' : order.status === 'CANCELED' ? '❌ 撤单' : '⏳ 挂起'}</span></td></tr>))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="p-8 text-center text-muted-foreground text-xs">无追踪限价单</div>}
            </TabsContent>
          </Tabs>
        </div>
      </div>
      )}
    </div>
  )
}