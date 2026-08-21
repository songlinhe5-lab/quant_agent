/**
 * UIRF-16: 回测指标计算 Hook（use-backtest.ts 拆分）
 * 纯计算，无副作用，依赖 backtestResult / rawReturns / reproParams。
 */
import { useMemo } from 'react'
import { computeHistogram } from './backtest-utils'
import { extractReproducibilityBadge } from '@/features/backtest/reproducibility-badge'

export function useBacktestMetrics(
  backtestResult: any,
  rawReturns: number[],
  reproParams: { atr_multiplier: number; commission_pct: number; slippage_pct: number; random_seed: number },
) {
  const histogramData = useMemo(() => {
    if (rawReturns.length > 0) return computeHistogram(rawReturns, 40)
    return []
  }, [rawReturns])

  const underwaterDataComputed = useMemo(() => {
    if (!backtestResult?.equity_curve) return []
    let maxEq = 0
    return backtestResult.equity_curve.map((d: any, i: number) => {
      if (d.equity > maxEq) maxEq = d.equity
      const dd = maxEq > 0 ? ((d.equity - maxEq) / maxEq) * 100 : 0
      return { t: i, dd }
    })
  }, [backtestResult])

  let runningMax = 0
  const curve = useMemo(() => {
    const baseData = backtestResult?.equity_curve || []
    return baseData.map((d: any, i: number) => {
      const eq = d.equity !== undefined ? d.equity : d.strategy
      // eslint-disable-next-line react-hooks/exhaustive-deps
      if (eq > runningMax) runningMax = eq
      const dayTrades = backtestResult?.trades?.filter((t: any) => t.date === d.date)
      let action = null
      let profit = 0
      if (dayTrades && dayTrades.length > 0) {
        action = dayTrades[dayTrades.length - 1].action
        profit = dayTrades.reduce((sum: number, t: any) => sum + (t.profit || 0), 0)
      }
      return {
        t: i, date: d.date, strategy: eq, benchmark: d.benchmark,
        tradeAction: action, tradeProfit: profit !== 0 ? profit : undefined,
        drawdownRange: [eq, runningMax],
      }
    })
  }, [backtestResult])

  const metrics = backtestResult?.metrics || {}

  const reproBadge = extractReproducibilityBadge(backtestResult) || {
    atr_multiplier: reproParams.atr_multiplier,
    commission_pct: reproParams.commission_pct,
    slippage_pct: reproParams.slippage_pct,
    random_seed: reproParams.random_seed,
  }

  const currentTearSheet = backtestResult
    ? [
        { label: '总收益率', value: metrics.total_return, dir: parseFloat(metrics.total_return) > 0 ? 1 : -1, note: '相对初始本金' },
        { label: '年化收益率', value: metrics.annualized_return, dir: parseFloat(metrics.annualized_return) > 0 ? 1 : -1, note: 'CAGR' },
        { label: '夏普比率', value: metrics.sharpe_ratio, dir: parseFloat(metrics.sharpe_ratio) > 1 ? 1 : -1, note: '基准: > 1.0' },
        { label: '最大回撤', value: metrics.max_drawdown, dir: -1, note: 'Max DD' },
        { label: '胜率', value: metrics.win_rate, dir: parseFloat(metrics.win_rate) > 50 ? 1 : -1, note: '盈利次数占比' },
        { label: '总交易次数', value: String(metrics.total_trades), dir: 0, note: '' },
        { label: '盈亏比', value: metrics.profit_factor, dir: parseFloat(metrics.profit_factor) > 1 ? 1 : -1, note: 'P/L Ratio' },
        { label: '摩擦成本', value: metrics.total_friction_cost, dir: -1, note: '手续费+滑点' },
      ]
    : []

  return { histogramData, underwaterDataComputed, curve, metrics, reproBadge, currentTearSheet }
}
