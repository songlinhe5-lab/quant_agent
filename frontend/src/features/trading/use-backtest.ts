/**
 * 回测模块核心 Hook：状态管理 + 业务逻辑
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { LATEST_PUBLISHED } from '@/types/datalake'
import { computeHistogram } from './backtest-utils'
import { runCustomExprBacktest } from '../quotes/custom-indicator/engine'
import { extractReproducibilityBadge } from '@/features/backtest/reproducibility-badge'

export function useBacktest() {
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressStage, setProgressStage] = useState('')
  const [rawReturns, setRawReturns] = useState<number[]>([])
  // UIRF-02: 回测错误态（错误卡 + 重试，禁止「报错也显示完成」）
  const [error, setError] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const [ticker, setTicker] = useState('US.NVDA')
  const [period, setPeriod] = useState('2y')
  const [interval, setIntervalVal] = useState('1d')
  const [initialCapital, setInitialCapital] = useState(100000)
  const [backtestResult, setBacktestResult] = useState<any>(null)
  const [dataSource, setDataSource] = useState('auto')
  const [isDebugMode, setIsDebugMode] = useState(false)
  const [dataSnapshotId, setDataSnapshotId] = useState(LATEST_PUBLISHED)
  // 💡 PROD-11 追问：自定义指标脚本表达式（作为回测信号源）
  const [customExpr, setCustomExpr] = useState('')

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
    setProgressStage('')
    toast({ variant: 'destructive', title: '🚨 回测已中止', description: '您手动取消了回测推演。' })
  }

  const handleRun = async (overrideParams?: Record<string, any>, isSilent: boolean = false) => {
    if (done || running) return
    setRunning(true)
    setProgress(0)
    setProgressStage('')
    setError(null)
    if (!isSilent) setBacktestResult(null)
    setRawReturns([])

    abortControllerRef.current = new AbortController()

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
      // ── PROD-11 追问：自定义指标脚本策略（本地计算，复用真实历史 K 线）──
      if (selectedStrategy === '__custom_expr__') {
        const expr = customExpr.trim()
        if (!expr) {
          toast({ variant: 'destructive', title: '请输入自定义指标表达式', description: '例如：CROSS(MA(CLOSE,5), MA(CLOSE,20))' })
          return
        }
        const ktypeMap: Record<string, string> = { '1d': 'K_DAY', '1h': 'K_60M', '15m': 'K_15M', '5m': 'K_5M', '1m': 'K_1M' }
        const numMap: Record<string, number> = { '1mo': 22, '3mo': 66, '6mo': 126, '1y': 252, '2y': 504, '5y': 1260, 'max': 3000 }
        const ktype = ktypeMap[interval] || 'K_DAY'
        const num = numMap[period] || 252
        try {
          const histRes = await apiClient.get('/market/history', { ticker, ktype, num }, abortControllerRef.current!.signal)
          const raw = histRes?.data?.data
          if (!Array.isArray(raw) || raw.length < 2) {
            toast({ variant: 'destructive', title: 'K 线数据不足', description: `接口返回 ${Array.isArray(raw) ? raw.length : 0} 根 K 线` })
            return
          }
          const bars = (raw as any[]).map((k) => {
            const rawTime = k.time ?? k.date ?? k.t
            let timeStr: string
            if (typeof rawTime === 'number') timeStr = new Date(rawTime * (rawTime < 1e12 ? 1000 : 1)).toISOString().slice(0, 10)
            else timeStr = String(rawTime).slice(0, 10)
            return { time: timeStr, open: Number(k.open), high: Number(k.high), low: Number(k.low), close: Number(k.close), volume: Number(k.volume ?? 0) }
          })
          const r = runCustomExprBacktest(expr, bars, initialCapital)
          if (!r.ok) {
            toast({ variant: 'destructive', title: '表达式回测失败', description: r.error })
            return
          }
          setBacktestResult(r.result)
          setRawReturns(r.dailyReturns.length ? r.dailyReturns : [0])
          if (!isSilent) toast({ title: '✅ 自定义指标回测完成', description: `${r.result!.trades.filter((t) => t.action === 'SELL').length} 笔交易 · 总收益 ${r.result!.metrics.total_return}` })
        } catch (e: any) {
          if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.message === 'canceled') return
          toast({ variant: 'destructive', title: '行情获取失败', description: e.message })
        }
        return
      }

      setProgressStage('加载历史 K 线...')
      const res = await apiClient.stream('/backtest/run/stream', {
        ticker, period, interval,
        initial_capital: initialCapital,
        atr_multiplier: 2.0, commission_pct: 0.0005, slippage_pct: 0.001,
        data_source: dataSource, debug_mode: isDebugMode,
        data_snapshot_id: dataSnapshotId, random_seed: 42,
        source_code: sourceCode || undefined,
        class_name: strategyClassName || undefined,
        params: Object.keys(sanitizedParams).length > 0 ? sanitizedParams : undefined
      }, abortControllerRef.current.signal)

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalData: any = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, nl).trim()
          buffer = buffer.slice(nl + 1)
          if (!line) continue
          let msg: any
          try {
            msg = JSON.parse(line)
          } catch {
            continue
          }
          if (msg.type === 'result') {
            finalData = msg.data
          } else if (msg.type === 'error') {
            throw new Error(msg.message)
          } else if (typeof msg.progress === 'number') {
            setProgress(msg.progress)
            setProgressStage(msg.detail || msg.stage || '')
          }
        }
      }

      if (finalData?.status === 'success' && finalData.data) {
        // UIRF-02: 仅 {type:'result'} 且 success → 成功态
        setBacktestResult(finalData.data)
        setDone(true)
        if (!isSilent) toast({ title: '✅ 回测推演完成', description: `策略执行完毕，已生成 Tear Sheet。` })
        // UIRF-01: 删除 Box-Muller 随机高斯假收益；真实 dailyReturns 来自后端 result.data（若有）
        const realReturns = Array.isArray(finalData.data?.daily_returns) ? finalData.data.daily_returns : []
        setRawReturns(realReturns)
      } else if (finalData) {
        // UIRF-02: 后端返回非成功 → 错误态（进度停实际值，非 100）
        setError(finalData.message || '回测执行失败')
        if (!isSilent) toast({ variant: 'destructive', title: '回测失败', description: finalData.message })
      }
    } catch (e: any) {
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.message === 'canceled') return;
      // UIRF-02: 网络异常 → 错误态（进度停实际值，非 100）
      setError(`网络异常：${e.message}`)
      if (!isSilent) toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      // UIRF-02: 状态机 —— 仅成功才 done；错误态保留 error + 进度停实际值；abort 由 handleCancel 已置 running=false
      if (!abortControllerRef.current?.signal.aborted) {
        setRunning(false)
      }
    }
  }

  // ── Computed Data ──

  const histogramData = useMemo(() => {
    if (rawReturns.length > 0) return computeHistogram(rawReturns, 40)
    return []
  }, [rawReturns])

  const underwaterDataComputed = useMemo(() => {
    if (!backtestResult?.equity_curve) return [];
    let maxEq = 0;
    return backtestResult.equity_curve.map((d: any, i: number) => {
      if (d.equity > maxEq) maxEq = d.equity;
      const dd = maxEq > 0 ? ((d.equity - maxEq) / maxEq) * 100 : 0;
      return { t: i, dd };
    });
  }, [backtestResult])

  let runningMax = 0;
  const curve = useMemo(() => {
    const baseData = backtestResult?.equity_curve || [];
    return baseData.map((d: any, i: number) => {
      const eq = d.equity !== undefined ? d.equity : d.strategy;
// eslint-disable-next-line react-hooks/exhaustive-deps
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
  ] : []

  return {
    // state
    running, done, progress, progressStage, ticker, setTicker, period, setPeriod,
    interval, setIntervalVal, initialCapital, setInitialCapital,
    backtestResult, dataSource, setDataSource, isDebugMode, setIsDebugMode,
    dataSnapshotId, setDataSnapshotId, strategies, selectedStrategy,
    formSchema, strategyParams, isMounted,
    customExpr, setCustomExpr, error, setError,
    // computed
    histogramData, underwaterDataComputed, curve, metrics, reproBadge, currentTearSheet,
    // handlers
    handleRun, handleCancel, handleStrategyChange, setDone, setProgress, setStrategyParams,
  }
}
