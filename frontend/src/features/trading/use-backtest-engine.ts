/**
 * UIRF-16: 回测引擎 Hook（use-backtest.ts 拆分）
 * 运行状态 + handleRun/handleCancel（含 PROD-11 自定义指标本地回测、NDJSON 流式解析、UIRF-01/02 状态机）。
 */
import { useRef, useState } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { runCustomExprBacktest } from '../quotes/custom-indicator/engine'

export interface BacktestEngineConfig {
  ticker: string
  period: string
  interval: string
  initialCapital: number
  dataSource: string
  isDebugMode: boolean
  dataSnapshotId: string
  customExpr: string
  selectedStrategy: string
  sourceCode: string
  strategyClassName: string
  strategyParams: Record<string, any>
  formSchema: any[]
  reproParams: { atr_multiplier: number; commission_pct: number; slippage_pct: number; random_seed: number }
}

export function useBacktestEngine(
  config: BacktestEngineConfig,
  setBacktestResult: (v: any) => void,
) {
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressStage, setProgressStage] = useState('')
  const [error, setError] = useState<string | null>(null)
  // UIRF-01 状态机补全：手动停止态（明示已停止 + 可重新运行，不静默重置）
  const [stopped, setStopped] = useState(false)
  const [rawReturns, setRawReturns] = useState<number[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const { toast } = useToast()

  const {
    ticker, period, interval, initialCapital, dataSource, isDebugMode, dataSnapshotId,
    customExpr, selectedStrategy, sourceCode, strategyClassName, strategyParams, formSchema, reproParams,
  } = config

  const handleCancel = () => {
    abortControllerRef.current?.abort()
    setRunning(false)
    setDone(false)
    setStopped(true)
    setProgressStage('')
    toast({ variant: 'destructive', title: '🚨 回测已中止', description: '停止即断开流，后端任务异步取消；已产出的最后一次成功结果（若有）保留。' })
  }

  const handleRun = async (overrideParams?: Record<string, any>, isSilent: boolean = false) => {
    if (done || running) return
    setRunning(true)
    setProgress(0)
    setProgressStage('')
    setError(null)
    setStopped(false)
    if (!isSilent) setBacktestResult(null)
    setRawReturns([])

    abortControllerRef.current = new AbortController()

    const finalParams = overrideParams || strategyParams
    const sanitizedParams = { ...finalParams }
    formSchema.find((s) => s.class_name === strategyClassName)?.parameters.forEach((p: any) => {
      let val = sanitizedParams[p.name]
      if (val === '' || val === undefined || val === null) val = p.default
      if ((p.type === 'int' || p.type === 'float') && typeof val === 'string') {
        const firstNumStr = val.split(/[:,]/)[0]
        const parsed = p.type === 'int' ? parseInt(firstNumStr) : parseFloat(firstNumStr)
        sanitizedParams[p.name] = !isNaN(parsed) ? parsed : (p.default || 0)
      } else {
        sanitizedParams[p.name] = val
      }
    })

    try {
      // ── PROD-11 追问：自定义指标脚本策略（本地计算，复用真实历史 K 线）──
      if (selectedStrategy === '__custom_expr__') {
        const expr = customExpr.trim()
        if (!expr) {
          toast({ variant: 'destructive', title: '请输入自定义指标表达式', description: '例如：CROSS(MA(CLOSE,5), MA(CLOSE,20))' })
          return
        }
        const ktypeMap: Record<string, string> = { '1d': 'K_DAY', '1h': 'K_60M', '15m': 'K_15M', '5m': 'K_5M', '1m': 'K_1M' }
        const numMap: Record<string, number> = { '1mo': 22, '3mo': 66, '6mo': 126, '1y': 252, '2y': 504, '5y': 1260, max: 3000 }
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
        atr_multiplier: reproParams.atr_multiplier, commission_pct: reproParams.commission_pct, slippage_pct: reproParams.slippage_pct,
        data_source: dataSource, debug_mode: isDebugMode,
        data_snapshot_id: dataSnapshotId, random_seed: reproParams.random_seed,
        source_code: sourceCode || undefined,
        class_name: strategyClassName || undefined,
        params: Object.keys(sanitizedParams).length > 0 ? sanitizedParams : undefined,
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
        setBacktestResult(finalData.data)
        setDone(true)
        if (!isSilent) toast({ title: '✅ 回测推演完成', description: `策略执行完毕，已生成 Tear Sheet。` })
        const realReturns = Array.isArray(finalData.data?.daily_returns) ? finalData.data.daily_returns : []
        setRawReturns(realReturns)
      } else if (finalData) {
        setError(finalData.message || '回测执行失败')
        if (!isSilent) toast({ variant: 'destructive', title: '回测失败', description: finalData.message })
      }
    } catch (e: any) {
      // 手动中止（AbortController.abort）不算失败：fetch 抛 AbortError，apiClient 抛 CanceledError
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.name === 'AbortError' || e.message === 'canceled') return
      setError(`网络异常：${e.message}`)
      if (!isSilent) toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      if (!abortControllerRef.current?.signal.aborted) {
        setRunning(false)
      }
    }
  }

  return {
    running, done, progress, progressStage, error, rawReturns, stopped,
    handleRun, handleCancel, setDone, setProgress, setError,
  }
}
