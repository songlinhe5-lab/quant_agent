/**
 * STRAT-01a: Backtest Slice — 回测引擎状态 / 表单配置 / 寻优 / 结构化错误 (STRAT-04 预留)
 */
import { StateCreator } from 'zustand'
import type { StrategyStore } from '../index'

export interface StructuredError {
  exc_type: string
  exc_message: string
  lineno: number | null
  traceback: string
  debug_tail: string[]
}

export interface BacktestSlice {
  // Form Config
  formSchema: any[]
  setFormSchema: (schema: any[]) => void
  testTicker: string
  setTestTicker: (ticker: string) => void
  initialCapital: string
  setInitialCapital: (cap: string) => void
  backtestPeriod: string
  setBacktestPeriod: (period: string) => void
  dataSource: string
  setDataSource: (source: string) => void
  dataSnapshotId: string
  setDataSnapshotId: (id: string) => void
  isDebugMode: boolean
  setIsDebugMode: (debug: boolean) => void
  savedPresets: Record<string, Record<string, any>>
  setSavedPresets: (presets: Record<string, Record<string, any>>) => void
  lastUsedClassName: string
  setLastUsedClassName: (name: string) => void
  lastUsedParams: Record<string, any>
  setLastUsedParams: (params: Record<string, any>) => void

  // Backtest Engine State
  isSimulating: boolean
  setSimulating: (sim: boolean) => void
  backtestResult: any
  setBacktestResult: (res: any) => void
  runtimeError: string | null
  setRuntimeError: (err: string | null) => void
  isOptimizing: boolean
  setOptimizing: (opt: boolean) => void
  optimizationResults: any[] | null
  setOptimizationResults: (res: any[] | null) => void
  optimizedClassName: string
  setOptimizedClassName: (name: string) => void

  // STRAT-04 预留: structured error
  structuredError: StructuredError | null
  setStructuredError: (err: StructuredError | null) => void
}

export const createBacktestSlice: StateCreator<StrategyStore, [], [], BacktestSlice> = (set) => ({
  // Form Config
  formSchema: [],
  setFormSchema: (formSchema) => set({ formSchema }),
  testTicker: 'US.AAPL',
  setTestTicker: (testTicker) => set({ testTicker }),
  initialCapital: '100000',
  setInitialCapital: (initialCapital) => set({ initialCapital }),
  backtestPeriod: '1y',
  setBacktestPeriod: (backtestPeriod) => set({ backtestPeriod }),
  dataSource: 'auto',
  setDataSource: (dataSource) => set({ dataSource }),
  dataSnapshotId: 'latest_published',
  setDataSnapshotId: (dataSnapshotId) => set({ dataSnapshotId }),
  isDebugMode: false,
  setIsDebugMode: (isDebugMode) => set({ isDebugMode }),
  savedPresets: {},
  setSavedPresets: (savedPresets) => set({ savedPresets }),
  lastUsedClassName: '',
  setLastUsedClassName: (lastUsedClassName) => set({ lastUsedClassName }),
  lastUsedParams: {},
  setLastUsedParams: (lastUsedParams) => set({ lastUsedParams }),

  // Backtest Engine State
  isSimulating: false,
  setSimulating: (isSimulating) => set({ isSimulating }),
  backtestResult: null,
  setBacktestResult: (backtestResult) => set({ backtestResult }),
  runtimeError: null,
  setRuntimeError: (runtimeError) => set({ runtimeError }),
  isOptimizing: false,
  setOptimizing: (isOptimizing) => set({ isOptimizing }),
  optimizationResults: null,
  setOptimizationResults: (optimizationResults) => set({ optimizationResults }),
  optimizedClassName: '',
  setOptimizedClassName: (optimizedClassName) => set({ optimizedClassName }),

  // STRAT-04 预留
  structuredError: null,
  setStructuredError: (structuredError) => set({ structuredError }),
})
