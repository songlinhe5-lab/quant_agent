/**
 * 回测模块核心 Hook：状态管理 + 业务逻辑
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { LATEST_PUBLISHED } from '@/types/datalake'
import { computeHistogram, equityCurve, returnsHist, tearSheetMetrics, underwaterData } from './backtest-mock'
import { extractReproducibilityBadge } from '@/features/backtest/reproducibility-badge'

export function useBacktest() {
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

  const { toast } = useToast()
  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => {
    setIsMounted(true)
    apiClient.get('/strategy/list').then(res => {
      if (res.data?.status === 'success') setStrategies(res.data.data)
    }).catch(e => console.error(e))
  }, [])

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
        ticker, period, interval,
        initial_capital: initialCapital,
        atr_multiplier: 2.0, commission_pct: 0.0005, slippage_pct: 0.001,
        data_source: dataSource, debug_mode: isDebugMode,
        data_snapshot_id: dataSnapshotId, random_seed: 42,
        source_code: sourceCode || undefined,
        class_name: strategyClassName || undefined,
        params: Object.keys(sanitizedParams).length > 0 ? sanitizedParams : undefined
      }, { signal: abortControllerRef.current.signal })

      if (res.data?.status === 'success' && res.data.data) {
        setBacktestResult(res.data.data)
        if (!isSilent) toast({ title: '✅ 回测推演完成', description: `策略执行完毕，已生成 Tear Sheet。` })
        const generatedReturns = Array.from({length: 1000}, () => {
          let u = 0, v = 0;
          while(u === 0) u = Math.random();
          while(v === 0) v = Math.random();
          const z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
          return 0.05 + z * 0.08;
        });
        setRawReturns(generatedReturns);
      } else {
        toast({ variant: 'destructive', title: '回测失败', description: res.data?.message })
      }
    } catch (e: any) {
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.message === 'canceled') return;
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      if (!abortControllerRef.current?.signal.aborted) {
        if (iv) clearInterval(iv)
        setProgress(100)
        setTimeout(() => { setRunning(false); setDone(true) }, isSilent ? 0 : 400)
      }
    }
  }

  // ── Computed Data ──

  const histogramData = useMemo(() => {
    if (rawReturns.length > 0) return computeHistogram(rawReturns, 40)
    return returnsHist
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

  return {
    // state
    running, done, progress, ticker, setTicker, period, setPeriod,
    interval, setIntervalVal, initialCapital, setInitialCapital,
    backtestResult, dataSource, setDataSource, isDebugMode, setIsDebugMode,
    dataSnapshotId, setDataSnapshotId, strategies, selectedStrategy,
    formSchema, strategyParams, isMounted,
    // computed
    histogramData, underwaterDataComputed, curve, metrics, reproBadge, currentTearSheet,
    // handlers
    handleRun, handleCancel, handleStrategyChange, setDone, setProgress, setStrategyParams,
  }
}
