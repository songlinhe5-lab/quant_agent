'use client'

import { useTheme } from 'next-themes'
import { useBacktest } from './use-backtest'
import { BacktestConfig } from './backtest-config'
import { BacktestResults } from './backtest-results'

// ── Main Component ──────────────────────────────────────────────────────────

export function BacktestModule() {
  const bt = useBacktest()
  const { theme } = useTheme()

  if (!bt.isMounted) return null

  return (
    <div className="space-y-4">
      {/* Title */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-amber-500 dark:bg-amber-400 transition-colors duration-300" aria-hidden="true" />
        <h1 className="text-base font-bold tracking-tight">高频回测引擎</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Backtest Engine</span>
      </div>

      {/* Config + Launch */}
      <BacktestConfig
        running={bt.running}
        done={bt.done}
        progress={bt.progress}
        ticker={bt.ticker} setTicker={bt.setTicker}
        period={bt.period} setPeriod={bt.setPeriod}
        interval={bt.interval} setIntervalVal={bt.setIntervalVal}
        initialCapital={bt.initialCapital} setInitialCapital={bt.setInitialCapital}
        dataSource={bt.dataSource} setDataSource={bt.setDataSource}
        isDebugMode={bt.isDebugMode} setIsDebugMode={bt.setIsDebugMode}
        dataSnapshotId={bt.dataSnapshotId} setDataSnapshotId={bt.setDataSnapshotId}
        strategies={bt.strategies}
        selectedStrategy={bt.selectedStrategy}
        formSchema={bt.formSchema}
        strategyParams={bt.strategyParams}
        handleRun={bt.handleRun}
        handleCancel={bt.handleCancel}
        handleStrategyChange={bt.handleStrategyChange}
        setDone={bt.setDone}
        setProgress={bt.setProgress}
        setStrategyParams={bt.setStrategyParams}
      />

      {/* Results */}
      <BacktestResults
        backtestResult={bt.backtestResult}
        running={bt.running}
        isDebugMode={bt.isDebugMode}
        currentTearSheet={bt.currentTearSheet}
        reproBadge={bt.reproBadge}
        metrics={bt.metrics}
        curve={bt.curve}
        underwaterDataComputed={bt.underwaterDataComputed}
        histogramData={bt.histogramData}
      />
    </div>
  )
}
