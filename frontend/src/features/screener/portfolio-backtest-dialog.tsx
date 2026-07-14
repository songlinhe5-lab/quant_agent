'use client'

import React, { useState, useCallback } from 'react'
import { BarChart3, X, Loader2, TrendingUp, TrendingDown, Calendar } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

interface PortfolioBacktestDialogProps {
  symbols: string[]
  onClose: () => void
}

interface TearSheetMetrics {
  total_return: string
  annualized_return: string
  sharpe_ratio: string
  max_drawdown: string
  volatility: string
  win_rate: string
  calmar_ratio: string
  total_symbols: number
  rebalance_freq: string
}

interface EquityPoint {
  date: string
  equity: number
  drawdown: number
}

interface SymbolPerf {
  symbol: string
  total_return: number
  max_dd: number
  sharpe: number
}

interface BacktestResult {
  metrics: TearSheetMetrics
  equity_curve: EquityPoint[]
  per_symbol: SymbolPerf[]
  monthly_returns: number[][]
  longest_drawdown: { start: string | null; end: string | null; depth: number; duration_days: number }
}

export function PortfolioBacktestDialog({ symbols, onClose }: PortfolioBacktestDialogProps) {
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [period, setPeriod] = useState('1y')
  const [rebalance, setRebalance] = useState('monthly')

  const runBacktest = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.post('/screener/portfolio-backtest', {
        symbols,
        period,
        initial_capital: 100000,
        rebalance_freq: rebalance,
      })
      if (res.data?.status === 'success') {
        setResult(res.data.data)
      } else {
        toast({ variant: 'destructive', title: '回测失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '回测异常', description: e.response?.data?.detail || e.message })
    } finally {
      setLoading(false)
    }
  }, [symbols, period, rebalance, toast])

  const metricCards = result ? [
    { label: '总收益', value: result.metrics.total_return, dir: parseFloat(result.metrics.total_return) > 0 ? 1 : -1 },
    { label: '年化收益', value: result.metrics.annualized_return, dir: parseFloat(result.metrics.annualized_return) > 0 ? 1 : -1 },
    { label: '夏普比率', value: result.metrics.sharpe_ratio, dir: parseFloat(result.metrics.sharpe_ratio) > 1 ? 1 : -1 },
    { label: '最大回撤', value: result.metrics.max_drawdown, dir: -1 },
    { label: '波动率', value: result.metrics.volatility, dir: -1 },
    { label: '胜率', value: result.metrics.win_rate, dir: parseFloat(result.metrics.win_rate) > 50 ? 1 : -1 },
    { label: 'Calmar', value: result.metrics.calmar_ratio, dir: parseFloat(result.metrics.calmar_ratio) > 1 ? 1 : -1 },
  ] : []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold">组合回测 Tear Sheet</h2>
            <span className="text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded">{symbols.length} 只标的</span>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>

        {/* Controls */}
        {!result && (
          <div className="px-6 py-4 border-b border-border flex items-center gap-4 shrink-0">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">回测周期</label>
              <select value={period} onChange={(e) => setPeriod(e.target.value)} className="text-xs bg-background border border-border rounded px-2 py-1">
                <option value="3mo">3 个月</option>
                <option value="6mo">6 个月</option>
                <option value="1y">1 年</option>
                <option value="2y">2 年</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">再平衡</label>
              <select value={rebalance} onChange={(e) => setRebalance(e.target.value)} className="text-xs bg-background border border-border rounded px-2 py-1">
                <option value="buy_and_hold">买入持有</option>
                <option value="weekly">每周</option>
                <option value="monthly">每月</option>
              </select>
            </div>
            <Button onClick={runBacktest} disabled={loading} className="ml-auto gap-1.5">
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BarChart3 className="h-3.5 w-3.5" />}
              {loading ? '回测中...' : '开始回测'}
            </Button>
          </div>
        )}

        {/* Results */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
          {result && (
            <>
              {/* Metric Cards */}
              <div className="grid grid-cols-4 lg:grid-cols-7 gap-3">
                {metricCards.map((m, i) => (
                  <div key={i} className="bg-secondary/30 rounded-lg p-3 border border-border/40">
                    <div className="text-[10px] text-muted-foreground mb-1">{m.label}</div>
                    <div className={`text-sm font-bold font-mono ${m.dir > 0 ? 'text-green-500' : m.dir < 0 ? 'text-red-500' : 'text-foreground'}`}>
                      {m.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Equity Curve */}
              <div className="bg-secondary/20 rounded-lg p-4 border border-border/40">
                <h3 className="text-xs font-semibold text-muted-foreground mb-3 flex items-center gap-1.5">
                  <TrendingUp className="h-3.5 w-3.5" /> 净值曲线
                </h3>
                <div className="h-48 flex items-end gap-px">
                  {result.equity_curve.filter((_, i) => i % Math.max(1, Math.floor(result.equity_curve.length / 100)) === 0).map((pt, i, arr) => {
                    const minEq = Math.min(...result.equity_curve.map(p => p.equity))
                    const maxEq = Math.max(...result.equity_curve.map(p => p.equity))
                    const pct = maxEq > minEq ? ((pt.equity - minEq) / (maxEq - minEq)) * 100 : 50
                    return (
                      <div key={i} className="flex-1 bg-primary/60 hover:bg-primary rounded-t transition-colors" style={{ height: `${Math.max(2, pct)}%` }} title={`${pt.date}: ¥${pt.equity.toLocaleString()}`} />
                    )
                  })}
                </div>
              </div>

              {/* Per Symbol Table */}
              <div className="bg-secondary/20 rounded-lg p-4 border border-border/40">
                <h3 className="text-xs font-semibold text-muted-foreground mb-3">各标的表现</h3>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border/40 text-muted-foreground">
                      <th className="text-left py-2">标的</th>
                      <th className="text-right py-2">总收益</th>
                      <th className="text-right py-2">最大回撤</th>
                      <th className="text-right py-2">夏普</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.per_symbol.map((s, i) => (
                      <tr key={i} className="border-b border-border/20">
                        <td className="py-1.5 font-mono">{s.symbol}</td>
                        <td className={`py-1.5 text-right font-mono ${s.total_return > 0 ? 'text-green-500' : 'text-red-500'}`}>{s.total_return}%</td>
                        <td className="py-1.5 text-right font-mono text-red-500">{s.max_dd}%</td>
                        <td className="py-1.5 text-right font-mono">{s.sharpe}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Longest Drawdown */}
              {result.longest_drawdown.start && (
                <div className="bg-red-500/5 rounded-lg p-4 border border-red-500/20">
                  <h3 className="text-xs font-semibold text-red-500 mb-2 flex items-center gap-1.5">
                    <TrendingDown className="h-3.5 w-3.5" /> 最长回撤期
                  </h3>
                  <div className="text-xs text-muted-foreground flex gap-4">
                    <span>{result.longest_drawdown.start} ~ {result.longest_drawdown.end}</span>
                    <span className="font-mono text-red-500">{result.longest_drawdown.depth}%</span>
                    <span>{result.longest_drawdown.duration_days} 天</span>
                  </div>
                </div>
              )}

              <Button variant="outline" onClick={() => setResult(null)} className="w-full">重新回测</Button>
            </>
          )}

          {!result && !loading && (
            <div className="text-center py-12 text-muted-foreground">
              <BarChart3 className="h-12 w-12 mx-auto mb-4 opacity-30" />
              <p className="text-sm">配置回测参数后点击「开始回测」</p>
              <p className="text-xs mt-2">将对选中的 {symbols.length} 只标的构建等权组合并回测</p>
            </div>
          )}

          {loading && (
            <div className="text-center py-12">
              <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4 text-primary" />
              <p className="text-sm text-muted-foreground">正在获取历史数据并运行回测...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
