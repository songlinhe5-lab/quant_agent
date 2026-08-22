/**
 * 回测模块核心 Hook（UIRF-16 拆分后为编排层）：
 *  配置状态 + 策略加载 + 组合 useBacktestEngine / useBacktestMetrics。
 */
import { useEffect, useState } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { LATEST_PUBLISHED } from '@/types/datalake'
import { useBacktestEngine } from './use-backtest-engine'
import { useBacktestMetrics } from './use-backtest-metrics'

export function useBacktest() {
  // ── 配置状态 ──
  const [ticker, setTicker] = useState('US.NVDA')
  const [period, setPeriod] = useState('2y')
  const [interval, setIntervalVal] = useState('1d')
  const [initialCapital, setInitialCapital] = useState(100000)
  const [backtestResult, setBacktestResult] = useState<any>(null)
  const [dataSource, setDataSource] = useState('auto')
  const [isDebugMode, setIsDebugMode] = useState(false)
  const [dataSnapshotId, setDataSnapshotId] = useState(LATEST_PUBLISHED)
  const [customExpr, setCustomExpr] = useState('')

  // 💡 动态策略引入状态
  const [strategies, setStrategies] = useState<any[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [sourceCode, setSourceCode] = useState<string>('')
  const [strategyClassName, setStrategyClassName] = useState<string>('')
  const [strategyParams, setStrategyParams] = useState<Record<string, any>>({})
  const [formSchema, setFormSchema] = useState<any[]>([])

  // UIRF-05: 回测成本/复现参数显性化
  const [reproParams, setReproParams] = useState({ atr_multiplier: 2.0, commission_pct: 0.0005, slippage_pct: 0.001, random_seed: 42 })

  const [isMounted, setIsMounted] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    setIsMounted(true)
    apiClient.get('/strategy/list').then((res) => {
      if (res.data?.status === 'success') setStrategies(res.data.data)
    }).catch((e) => console.error(e))
  }, [])

  const handleStrategyChange = async (name: string) => {
    setSelectedStrategy(name)
    if (!name) {
      setSourceCode(''); setStrategyClassName(''); setStrategyParams({}); setFormSchema([])
      return
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

  // ── 引擎（运行状态 + handleRun/handleCancel）──
  const engine = useBacktestEngine(
    { ticker, period, interval, initialCapital, dataSource, isDebugMode, dataSnapshotId, customExpr, selectedStrategy, sourceCode, strategyClassName, strategyParams, formSchema, reproParams },
    setBacktestResult,
  )

  // ── 指标计算 ──
  const metricsCalc = useBacktestMetrics(backtestResult, engine.rawReturns, reproParams)

  return {
    // state
    running: engine.running, done: engine.done, progress: engine.progress, progressStage: engine.progressStage,
    ticker, setTicker, period, setPeriod,
    interval, setIntervalVal, initialCapital, setInitialCapital,
    backtestResult, dataSource, setDataSource, isDebugMode, setIsDebugMode,
    dataSnapshotId, setDataSnapshotId, strategies, selectedStrategy,
    formSchema, strategyParams, isMounted,
    customExpr, setCustomExpr, error: engine.error, setError: engine.setError, reproParams, setReproParams,
    // computed
    histogramData: metricsCalc.histogramData, underwaterDataComputed: metricsCalc.underwaterDataComputed,
    curve: metricsCalc.curve, metrics: metricsCalc.metrics, reproBadge: metricsCalc.reproBadge, currentTearSheet: metricsCalc.currentTearSheet,
    // handlers
    handleRun: engine.handleRun, handleCancel: engine.handleCancel, handleStrategyChange,
    setDone: engine.setDone, setProgress: engine.setProgress, setStrategyParams,
  }
}
