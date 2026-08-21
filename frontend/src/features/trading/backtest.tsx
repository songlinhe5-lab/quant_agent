'use client'

import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useBacktest } from './use-backtest'
import { InitOverlay } from '@/components/ui/data-display'
import { BacktestConfig } from './backtest-config'
import { BacktestResults } from './backtest-results'

// ── Main Component ──────────────────────────────────────────────────────────

export function BacktestModule() {
  const bt = useBacktest()

  // §14.2：初始化态给出可见反馈（骨架屏），禁止静默白屏或卡死
  if (!bt.isMounted) {
    return <InitOverlay variant="skeleton" label="正在初始化回测终端…" className="h-[calc(100vh-48px)] min-h-[400px]" />
  }

  return (
    <div className="space-y-4">
      {/* Title */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-amber-500 dark:bg-amber-400 transition-colors duration-300" aria-hidden="true" />
        <h1 className="text-base font-bold tracking-tight">高频回测引擎</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Backtest Engine</span>
        <span className="text-[10px] font-mono text-muted-foreground/60 border border-border/40 rounded px-1.5 py-0.5">独立大规模回测 · 端点 /backtest/run/stream</span>
        <Link
          to="/strategy"
          className="ml-auto flex items-center gap-1 text-[10px] text-blue-500 hover:text-blue-400 transition-colors"
          title="在工作台策略研发沙箱中打开 (端点 /strategy/run-sandbox/*)"
        >
          在工作台沙箱中打开 <ExternalLink className="h-3 w-3" />
        </Link>
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
        customExpr={bt.customExpr}
        setCustomExpr={bt.setCustomExpr}
      />

      {/* Results */}
      <BacktestResults
        backtestResult={bt.backtestResult}
        running={bt.running}
        progress={bt.progress}
        progressStage={bt.progressStage}
        isDebugMode={bt.isDebugMode}
        currentTearSheet={bt.currentTearSheet}
        reproBadge={bt.reproBadge}
        metrics={bt.metrics}
        curve={bt.curve}
        underwaterDataComputed={bt.underwaterDataComputed}
        histogramData={bt.histogramData}
        // UIRF-02: 错误态（错误卡 + 重试）
        error={bt.error}
        onRetry={() => { bt.setError(null); bt.setDone(false); bt.handleRun() }}
      />
    </div>
  )
}
