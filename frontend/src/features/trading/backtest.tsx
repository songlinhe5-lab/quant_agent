'use client'

import { useState, useEffect, useMemo, useRef} from 'react'
import { FlaskConical, Play, AlertTriangle, TrendingDown, BarChart3, CheckCircle, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { DynamicStrategyForm } from '@/features/strategy/dynamic-strategy-form'
import { BacktestEquityChart, BacktestUnderwaterChart, BacktestReturnsHistogram } from './backtest-charts'
import { SnapshotPicker } from '@/features/backtest/snapshot-picker'
import {
  ReproducibilityBadgeView,
  extractReproducibilityBadge,
} from '@/features/backtest/reproducibility-badge'
import { LATEST_PUBLISHED } from '@/types/datalake'

// ── Mock Data ───────────────────────────────────────────────────────────────

const equityCurve = Array.from({ length: 60 }, (_, i) => ({
  t: i,
  strategy: 100000 + i * 2000 + Math.sin(i * 0.4) * 8000 + Math.random() * 3000,
  benchmark: 100000 + i * 1000 + Math.sin(i * 0.2) * 3000,
}))

const underwaterData = Array.from({ length: 60 }, (_, i) => ({
  t: i,
  dd: -Math.abs(Math.sin(i * 0.15) * 12 + Math.random() * 3),
}))

const returnsHist = [
  { range: '< -5%',  count: 12,  color: '#f87171', lightColor: '#dc2626' },
  { range: '-5~-3%', count: 28,  color: '#fca5a5', lightColor: '#ef4444' },
  { range: '-3~-1%', count: 67,  color: '#fcd34d', lightColor: '#f59e0b' },
  { range: '-1~0%',  count: 89,  color: '#d1d5db', lightColor: '#9ca3af' },
  { range: '0~1%',   count: 156, color: '#6ee7b7', lightColor: '#10b981' },
  { range: '1~3%',   count: 412, color: '#34d399', lightColor: '#059669' },
  { range: '3~5%',   count: 234, color: '#10b981', lightColor: '#047857' },
  { range: '> 5%',   count: 58,  color: '#059669', lightColor: '#064e3b' },
]

// 💡 将连续的 Float 数组 (如 Monte Carlo 的 raw_returns) 分箱为离散的直方图数据
function computeHistogram(rawReturns: number[], binsCount = 30) {
  if (!rawReturns || rawReturns.length === 0) return []
  const min = Math.min(...rawReturns)
  const max = Math.max(...rawReturns)
  const step = (max - min) / binsCount

  const bins = Array.from({ length: binsCount }, (_, i) => {
    const rangeMin = min + i * step
    const rangeMax = min + (i + 1) * step
    return {
      rangeMin, rangeMax, count: 0,
      range: `${(rangeMin * 100).toFixed(1)}%~${(rangeMax * 100).toFixed(1)}%`,
      // 动态颜色：亏损用红色系，盈利段用绿色系，零轴附近用中性色
      color: rangeMax <= 0 ? '#f87171' : rangeMin >= 0 ? '#34d399' : '#9ca3af',
      lightColor: rangeMax <= 0 ? '#dc2626' : rangeMin >= 0 ? '#059669' : '#4b5563',
    }
  })

  rawReturns.forEach(r => {
    let index = Math.floor((r - min) / step)
    if (index >= binsCount) index = binsCount - 1
    if (index < 0) index = 0
    bins[index].count++
  })

  return bins
}

const tearSheetMetrics = [
  { label: '年化收益率', value: '24.5%',  dir: 1,  note: '总收益 +124.5%' },
  { label: '夏普比率',   value: '2.34',   dir: 1,  note: '基准: > 1.0' },
  { label: '卡玛比率',   value: '1.98',   dir: 1,  note: '收益/最大回撤' },
  { label: '最大回撤',   value: '-12.3%', dir: -1, note: '持续 47 天' },
  { label: '胜率',       value: '62.1%',  dir: 1,  note: '盈亏比: 1.8x' },
  { label: '总交易次数', value: '1,247',  dir: 0,  note: '均持仓: 2.3天' },
  { label: 'Sortino',    value: '3.12',   dir: 1,  note: '仅负回报波动' },
  { label: 'Omega',      value: '1.72',   dir: 1,  note: '>1.0 为正期望' },
]

// ── Main Component ──────────────────────────────────────────────────────────

export function BacktestModule() {
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [progress, setProgress] = useState(0)
  const [rawReturns, setRawReturns] = useState<number[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  
  const [ticker, setTicker] = useState('US.NVDA')
  const [period, setPeriod] = useState('2y')
  const [interval, setIntervalVal] = useState('1d')
  const [initialCapital, setInitialCapital] = useState(100000)
  const [backtestResult, setBacktestResult] = useState<any>(null)
  const [dataSource, setDataSource] = useState('auto')
  const [isDebugMode, setIsDebugMode] = useState(false)
  const [dataSnapshotId, setDataSnapshotId] = useState(LATEST_PUBLISHED)
  
  // 💡 动态策略引入状态
  const [strategies, setStrategies] = useState<any[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [sourceCode, setSourceCode] = useState<string>('')
  const [strategyClassName, setStrategyClassName] = useState<string>('')
  const [strategyParams, setStrategyParams] = useState<Record<string, any>>({})
  const [formSchema, setFormSchema] = useState<any[]>([])

  const { theme } = useTheme()
  const { toast } = useToast()

  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => {
    setIsMounted(true)
    // 初始化时拉取草稿箱策略列表
    apiClient.get('/strategy/list').then(res => {
      if (res.data?.status === 'success') setStrategies(res.data.data)
    }).catch(e => console.error(e))
  }, [])

  // 💡 监听下拉框策略切换，自动解析参数生成表单
  const handleStrategyChange = async (name: string) => {
    setSelectedStrategy(name)
    if (!name) {
      setSourceCode(''); setStrategyClassName(''); setStrategyParams({}); setFormSchema([]);
      return;
    }
    try {
      const draftRes = await apiClient.get(`/strategy/draft/${name}`)
      if (draftRes.data?.status === 'success') {
        const code = draftRes.data.data.source_code
        setSourceCode(code)
        const parseRes = await apiClient.post('/strategy/parse-config', { source_code: code })
        if (parseRes.data?.status === 'success' && parseRes.data.data) {
          setFormSchema(parseRes.data.data)
          const schema = parseRes.data.data[0]
          if (schema) {
            setStrategyClassName(schema.class_name)
            const defaultParams: Record<string, any> = {}
            schema.parameters.forEach((p: any) => {
              defaultParams[p.name] = p.default !== null ? p.default : ''
            })
            setStrategyParams(defaultParams)
          }
        }
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '策略加载失败', description: e.message })
    }
  }

  // 💡 中止回测逻辑
  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setRunning(false)
    setDone(false)
    setProgress(0)
    toast({ variant: 'destructive', title: '🚨 回测已中止', description: '您手动取消了回测推演。' })
  }

  const handleRun = async (overrideParams?: Record<string, any>, isSilent: boolean = false) => {
    if (done || running) return
    setRunning(true)
    if (!isSilent) setBacktestResult(null)
    setRawReturns([])
    
    abortControllerRef.current = new AbortController()

    let p = 0
    let iv: any;
    if (!isSilent) {
      iv = setInterval(() => {
        p += Math.random() * 15 + 5
        if (p >= 90) p = 90;
        setProgress(p)
      }, 300)
    }
    
    // 清洗参数：网格语法降级为单次探测防崩溃
    const finalParams = overrideParams || strategyParams
    const sanitizedParams = { ...finalParams }
    formSchema.find(s => s.class_name === strategyClassName)?.parameters.forEach((p: any) => {
      let val = sanitizedParams[p.name];
      if (val === '' || val === undefined || val === null) val = p.default;
      
      if ((p.type === 'int' || p.type === 'float') && typeof val === 'string') {
        const firstNumStr = val.split(/[:,]/)[0]
        const parsed = p.type === 'int' ? parseInt(firstNumStr) : parseFloat(firstNumStr);
        sanitizedParams[p.name] = !isNaN(parsed) ? parsed : (p.default || 0);
      } else {
        sanitizedParams[p.name] = val;
      }
    });

    try {
      const res = await apiClient.post('/backtest/run', {
        ticker,
        period,
        interval,
        initial_capital: initialCapital,
        atr_multiplier: 2.0,
        commission_pct: 0.0005,
        slippage_pct: 0.001,
        data_source: dataSource,
        debug_mode: isDebugMode,
        data_snapshot_id: dataSnapshotId,
        random_seed: 42,
        source_code: sourceCode || undefined,
        class_name: strategyClassName || undefined,
        params: Object.keys(sanitizedParams).length > 0 ? sanitizedParams : undefined
      }, { signal: abortControllerRef.current.signal })
      
      if (res.data?.status === 'success' && res.data.data) {
         setBacktestResult(res.data.data)
         if (!isSilent) toast({ title: '✅ 回测推演完成', description: `策略执行完毕，已生成 Tear Sheet。` })
         
        // 💡 Mock：模拟后端 Monte Carlo 引擎返回的正态分布 (Gaussian) 收益率数组，共 1000 次迭代
        const generatedReturns = Array.from({length: 1000}, () => {
          // 使用 Box-Muller 变换生成正态分布随机数
          let u = 0, v = 0;
          while(u === 0) u = Math.random();
          while(v === 0) v = Math.random();
          const z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
          return 0.05 + z * 0.08; // 模拟均值 5%，标准差 8% 的策略分布
        });
        setRawReturns(generatedReturns);
      } else {
         toast({ variant: 'destructive', title: '回测失败', description: res.data?.message })
      }
    } catch (e: any) {
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.message === 'canceled') {
        return;
      }
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      if (!abortControllerRef.current?.signal.aborted) {
        if (iv) clearInterval(iv)
        setProgress(100)
        setTimeout(() => {
          setRunning(false)
          setDone(true)
        }, isSilent ? 0 : 400)
      }
    }
  }

  const histogramData = useMemo(() => {
    if (rawReturns.length > 0) return computeHistogram(rawReturns, 40)
    return returnsHist // fallback to static mock
  }, [rawReturns])

  const underwaterDataComputed = useMemo(() => {
    if (!backtestResult?.equity_curve) return underwaterData;
    let maxEq = 0;
    return backtestResult.equity_curve.map((d: any, i: number) => {
      if (d.equity > maxEq) maxEq = d.equity;
      const dd = maxEq > 0 ? ((d.equity - maxEq) / maxEq) * 100 : 0;
      return { t: i, dd };
    });
  }, [backtestResult])

  let runningMax = 0;
  const curve = useMemo(() => {
    const baseData = backtestResult?.equity_curve || equityCurve;
    return baseData.map((d: any, i: number) => {
      const eq = d.equity !== undefined ? d.equity : d.strategy;
      if (eq > runningMax) runningMax = eq;
      
      const dayTrades = backtestResult?.trades?.filter((t: any) => t.date === d.date);
      let action = null;
      let profit = 0;
      if (dayTrades && dayTrades.length > 0) {
        action = dayTrades[dayTrades.length - 1].action;
        profit = dayTrades.reduce((sum: number, t: any) => sum + (t.profit || 0), 0);
      }
      
      return {
        t: i, date: d.date, strategy: eq, benchmark: d.benchmark,
        tradeAction: action, tradeProfit: profit !== 0 ? profit : undefined,
        drawdownRange: [eq, runningMax]
      }
    });
  }, [backtestResult]);

  if (!isMounted) return null
  
  const isDark = theme === 'dark'

  const metrics = backtestResult?.metrics || {}
  const reproBadge = extractReproducibilityBadge(backtestResult)

  const currentTearSheet = backtestResult ? [
    { label: '总收益率',   value: metrics.total_return,  dir: parseFloat(metrics.total_return) > 0 ? 1 : -1,  note: '相对初始本金' },
    { label: '年化收益率', value: metrics.annualized_return,  dir: parseFloat(metrics.annualized_return) > 0 ? 1 : -1,  note: 'CAGR' },
    { label: '夏普比率',   value: metrics.sharpe_ratio,   dir: parseFloat(metrics.sharpe_ratio) > 1 ? 1 : -1,  note: '基准: > 1.0' },
    { label: '最大回撤',   value: metrics.max_drawdown, dir: -1, note: 'Max DD' },
    { label: '胜率',       value: metrics.win_rate,  dir: parseFloat(metrics.win_rate) > 50 ? 1 : -1,  note: '盈利次数占比' },
    { label: '总交易次数', value: String(metrics.total_trades),  dir: 0,  note: '' },
    { label: '盈亏比',      value: metrics.profit_factor,   dir: parseFloat(metrics.profit_factor) > 1 ? 1 : -1,  note: 'P/L Ratio' },
    { label: '摩擦成本',    value: metrics.total_friction_cost,   dir: -1,  note: '手续费+滑点' },
  ] : tearSheetMetrics

  return (
    <div className="space-y-4">
      {/* Title */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-amber-500 dark:bg-amber-400 transition-colors duration-300" aria-hidden="true" />
        <h1 className="text-base font-bold tracking-tight">高频回测引擎</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Backtest Engine</span>
      </div>

      {/* Config + Launch */}
      <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">回测配置</span>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 mb-4">
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">执行策略</p>
              <select value={selectedStrategy} onChange={e => handleStrategyChange(e.target.value)} disabled={running || done} className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary w-full cursor-pointer">
                <option value="">内置底背离共振 (默认)</option>
                {strategies.map((s, i) => (
                  <option key={i} value={s.name}>{s.name}</option>
                ))}
              </select>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">测试标的</p>
              <input 
                type="text" 
                value={ticker} 
                onChange={e => setTicker(e.target.value.toUpperCase())} 
                className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary font-mono uppercase w-full" 
                disabled={running || done}
              />
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">回测区间</p>
              <select value={period} onChange={e => setPeriod(e.target.value)} disabled={running || done} className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary w-full cursor-pointer">
                <option value="1mo">1 个月</option>
                <option value="3mo">3 个月</option>
                <option value="6mo">6 个月</option>
                <option value="1y">1 年</option>
                <option value="2y">2 年</option>
                <option value="5y">5 年</option>
                <option value="max">全部历史</option>
              </select>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">数据粒度</p>
              <select value={interval} onChange={e => setIntervalVal(e.target.value)} disabled={running || done} className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary w-full cursor-pointer">
                <option value="1d">1 日 (1d)</option>
                <option value="1h">1 小时 (1h)</option>
                <option value="15m">15 分钟 (15m)</option>
                <option value="5m">5 分钟 (5m)</option>
                <option value="1m">1 分钟 (1m)</option>
              </select>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">初始资金</p>
              <input type="number" value={initialCapital} onChange={e => setInitialCapital(Number(e.target.value))} disabled={running || done} className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary font-mono w-full tabular-nums" />
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">数据源</p>
              <select value={dataSource} onChange={e => setDataSource(e.target.value)} disabled={running || done} className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary w-full cursor-pointer">
                <option value="auto">智能路由 (Auto)</option>
                <option value="futu">富途 OpenD (Futu)</option>
                <option value="yfinance">雅虎财经 (YFinance)</option>
              </select>
            </div>
            <div>
              <p className="text-[10px] text-muted-foreground mb-1">调试模式</p>
              <div className="flex items-center gap-2 h-[26px]">
                <input 
                  type="checkbox" 
                  id="debugModeBT" 
                  checked={isDebugMode} 
                  onChange={(e) => setIsDebugMode(e.target.checked)}
                  className="rounded-sm border-border accent-primary focus:ring-primary/30 w-3.5 h-3.5 cursor-pointer"
                />
                <label htmlFor="debugModeBT" className="text-xs text-muted-foreground cursor-pointer select-none">记录逐K线日志</label>
              </div>
            </div>
          </div>

          <div className="mb-4 max-w-md">
            <SnapshotPicker
              value={dataSnapshotId}
              onChange={setDataSnapshotId}
              disabled={running || done}
            />
          </div>

          {running && (
            <div className="mb-4 p-3 rounded-lg bg-secondary/40 border border-border/30">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold font-mono flex items-center gap-1.5">
                  回测进行中…
                  <button onClick={handleCancel} className="p-0.5 rounded bg-red-500/10 hover:bg-red-500/20 text-red-500 transition-colors" title="中止回测"><Square className="h-3 w-3 fill-current" /></button>
                </span>
                <span className="text-xs font-mono tabular-nums text-primary">{Math.round(progress)}%</span>
              </div>
              <div className="h-2 bg-secondary rounded-full overflow-hidden">
                <div className="h-full bg-primary rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
              </div>
              <div className="mt-2 bg-slate-50 dark:bg-[oklch(0.09_0.005_270)] rounded p-2 font-mono text-[10px] text-muted-foreground space-y-0.5 max-h-20 overflow-y-auto transition-colors duration-300">
                <div><span className="text-sky-600 dark:text-sky-400 transition-colors duration-300">[INFO]</span> 加载历史数据 2024-01-01 ~ 2026-06-01…</div>
                <div><span className="text-sky-600 dark:text-sky-400 transition-colors duration-300">[INFO]</span> 初始化策略模块 PairsTradingBot…</div>
                <div><span className="text-emerald-600 dark:text-emerald-400 transition-colors duration-300">[TRADE]</span> 2024-03-15 检测信号 Z-Score=2.73 → 开多</div>
                <div><span className="text-emerald-600 dark:text-emerald-400 transition-colors duration-300">[TRADE]</span> 累计成交 {Math.round(progress * 12)} 笔…</div>
              </div>
            </div>
          )}

          {/* 💡 动态策略参数表单：根据选择的策略热插拔渲染 */}
          {formSchema.length > 0 && (
            <div className="mb-4 pt-4 border-t border-border/30 animate-in fade-in slide-in-from-top-2">
              <DynamicStrategyForm 
                schema={formSchema} 
                onSubmit={(className, data, isSilent) => {
                  setStrategyParams(data);
                  handleRun(data, isSilent);
                }} 
              />
            </div>
          )}

          <div className="flex gap-2 flex-wrap">
            {formSchema.length === 0 && (
              <>
                <Button
                  className="gap-2 text-sm"
                  onClick={() => handleRun()}
                  disabled={running || done}
                >
                  {done
                    ? <><CheckCircle className="h-4 w-4" aria-hidden="true" />回测完成</>
                    : running
                      ? <><FlaskConical className="h-4 w-4 animate-spin" aria-hidden="true" />运行中…</>
                      : <><Play className="h-4 w-4" aria-hidden="true" />启动回测 (Serverless)</>
                  }
                </Button>
                {running && (
                  <Button variant="destructive" className="gap-2 text-sm h-9" onClick={handleCancel}>
                    <Square className="h-4 w-4 fill-current" /> 中止
                  </Button>
                )}
              </>
            )}
            {done && (
              <Button variant="outline" size="sm" className="text-xs h-9" onClick={() => { setDone(false); setProgress(0) }}>
                重新回测
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Disclaimer banner */}
      <div className="flex items-start gap-3 px-4 py-3 rounded-lg bg-amber-500/10 dark:bg-amber-400/8 border border-amber-500/20 dark:border-amber-400/20 transition-colors duration-300">
        <AlertTriangle className="h-4 w-4 text-amber-500 dark:text-amber-400 flex-shrink-0 mt-0.5 transition-colors duration-300" aria-hidden="true" />
        <p className="text-xs text-amber-700 dark:text-amber-300/80 leading-relaxed transition-colors duration-300">
          <span className="font-bold">免责声明：</span>回测结果仅供参考，不代表未来实盘收益。历史数据可能含有幸存者偏差，实际运行中的滑点、手续费、流动性约束均会导致结果偏差。严禁将回测夏普比率直接作为实盘风控依据。
        </p>
      </div>

      {/* Tear Sheet KPIs */}
      <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Tear Sheet · 核心指标</span>
          </div>
          <ReproducibilityBadgeView badge={reproBadge} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y divide-border/20">
          {currentTearSheet.map((m, i) => (
            <div key={i} className="px-4 py-3">
              <p className="text-[10px] text-muted-foreground mb-1">{m.label}</p>
              <p className={cn(
                'text-lg font-bold font-mono tabular-nums leading-tight transition-colors duration-300',
                m.dir > 0 ? 'text-emerald-600 dark:text-emerald-400' : m.dir < 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground'
              )}>{m.value}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">{m.note}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Charts Tabs */}
      <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
        <Tabs defaultValue="equity">
          <div className="border-b border-border/30 px-4">
            <TabsList className="bg-transparent p-0 gap-0 h-10">
              {[['equity','权益曲线'],['drawdown','水下时间'],['returns','收益分布'],['trades','交易明细'],['limit_orders','限价单'], ['debug_logs','调试日志']].map(([v, l]) => (
                <TabsTrigger key={v} value={v} className="text-xs px-3 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                  {l}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value="equity" className="m-0 p-4">
            <div className="h-52">
              <BacktestEquityChart data={curve} />
            </div>
            <div className="flex gap-4 mt-2 text-[10px]">
              <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-emerald-500 dark:bg-emerald-400 rounded transition-colors duration-300" />策略净值</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground/40" />基准收益</span>
            </div>
          </TabsContent>

          <TabsContent value="drawdown" className="m-0 p-4">
            <div className="h-52">
              <BacktestUnderwaterChart data={underwaterDataComputed} maxDrawdown={metrics.max_drawdown} />
            </div>
          </TabsContent>

          <TabsContent value="returns" className="m-0 p-4">
            <div className="h-52">
              <BacktestReturnsHistogram data={histogramData} />
            </div>
          </TabsContent>

          <TabsContent value="trades" className="m-0">
            <div className="overflow-x-auto max-h-52 custom-scrollbar">
              <table className="w-full text-xs" aria-label="交易明细">
                <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md">
                  <tr className="border-b border-border/30 bg-secondary/20">
                    <th className="px-4 py-2 text-left text-muted-foreground font-medium">日期</th>
                    <th className="px-4 py-2 text-left text-muted-foreground font-medium">方向</th>
                    <th className="px-4 py-2 text-right text-muted-foreground font-medium">成交价</th>
                    <th className="px-4 py-2 text-right text-muted-foreground font-medium">股数</th>
                    <th className="px-4 py-2 text-right text-muted-foreground font-medium">平仓盈亏</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/15">
                  {backtestResult?.trades ? backtestResult.trades.map((trade: any, i: number) => (
                    <tr key={i} className="hover:bg-secondary/25 transition-colors">
                      <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{trade.date}</td>
                      <td className="px-4 py-2.5 font-bold">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px]", trade.action === 'BUY' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400')}>
                          {trade.action}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums">${Number(trade.price).toFixed(2)}</td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-muted-foreground">{trade.shares}</td>
                      <td className={cn('px-4 py-2.5 text-right font-mono font-bold tabular-nums transition-colors duration-300', trade.profit > 0 ? 'text-emerald-600 dark:text-emerald-400' : trade.profit < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                        {trade.action === 'SELL' ? (trade.profit > 0 ? `+$${Number(trade.profit).toFixed(2)}` : `-$${Math.abs(Number(trade.profit)).toFixed(2)}`) : '-'}
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground text-xs">
                        {running ? '回测执行中...' : '暂无交易记录'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="limit_orders" className="m-0">
            <div className="overflow-x-auto max-h-52 custom-scrollbar">
              <table className="w-full text-xs" aria-label="限价单明细">
                <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md">
                  <tr className="border-b border-border/30 bg-secondary/20">
                    <th className="px-4 py-2 text-left text-muted-foreground font-medium">挂单日</th>
                    <th className="px-4 py-2 text-left text-muted-foreground font-medium">终结日</th>
                    <th className="px-4 py-2 text-right text-muted-foreground font-medium">限价</th>
                    <th className="px-4 py-2 text-center text-muted-foreground font-medium">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/15">
                  {backtestResult?.limit_orders && backtestResult.limit_orders.length > 0 ? backtestResult.limit_orders.map((order: any, i: number) => (
                    <tr key={i} className="hover:bg-secondary/25 transition-colors">
                      <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{order.start_date}</td>
                      <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{order.end_date}</td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-amber-500 font-bold">${Number(order.price).toFixed(2)}</td>
                      <td className="px-4 py-2.5 text-center">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold border", 
                          order.status === 'FILLED' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30' : 
                          order.status === 'CANCELED' ? 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30' : 
                          'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
                        )}>
                          {order.status}
                        </span>
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground text-xs">
                        {running ? '回测执行中...' : '暂无追踪限价单记录'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="debug_logs" className="m-0">
            <div className="overflow-x-auto max-h-52 custom-scrollbar bg-black/90 p-3 rounded-b-lg">
              {backtestResult?.debug_logs && backtestResult.debug_logs.length > 0 ? (
                <div className="text-[10px] font-mono text-emerald-400/90 whitespace-pre-wrap leading-relaxed">
                  {backtestResult.debug_logs.join('\n')}
                </div>
              ) : (
                <div className="text-center text-muted-foreground text-xs py-8">
                  {isDebugMode ? '无有效交易引发的内部状态更新' : '未开启 Debug 模式。请在上方配置中勾选后重新执行。'}
                </div>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
