'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api-client'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'
import { WfInterpretData } from './backtest-walkforward-panel'

interface InterpretData {
  summary: string
  source: string
  confidence: number
}

interface OverfitData {
  overfit: boolean
  max_sensitivity: number
  threshold: number
}

interface ParamSweepInput {
  param: string
  sharpe: string
}

interface BacktestInterpretPanelProps {
  backtestResult: Record<string, any> | null | undefined
  walkForward?: WfInterpretData | null
}

/**
 * AI-03 回测工坊·报告解读员面板。
 * - 自动基于真实回测指标调用 /backtest/interpret 生成 ≤80 字解读（含杠杆/Alpha 判别）。
 * - 携带 walkForward 时把过拟合/Alpha 衰减信号织入主解读，做单一联合研判。
 * - 提供参数敏感性过拟合检测（纯计算），结果来自 /backtest/overfit-check。
 * 受 AI-09 推送偏好底座 `ai03` 开关统一管控。
 */
export function BacktestInterpretPanel({ backtestResult, walkForward }: BacktestInterpretPanelProps) {
  const ai03Enabled = useAiPushPrefStore((s) => s.isEnabled('ai03'))

  const [interpret, setInterpret] = useState<InterpretData | null>(null)
  const [interpreting, setInterpreting] = useState(false)
  const [interpretError, setInterpretError] = useState<string | null>(null)
  const [overfit, setOverfit] = useState<OverfitData | null>(null)
  const [sweeps, setSweeps] = useState<ParamSweepInput[]>([{ param: 'lookback', sharpe: '' }])

  const metrics = (backtestResult?.metrics || {}) as Record<string, any>
  const symbol = backtestResult?.symbol
  const leverage = Number(backtestResult?.params?.leverage ?? 1.0)

  const annualReturn = Number(metrics.annualized_return ?? metrics.annual_return ?? 0)
  const sharpe = Number(metrics.sharpe_ratio ?? 0)
  const mdd = Math.abs(Number(metrics.max_drawdown ?? 0))
  const hasMetrics = annualReturn !== 0 || sharpe !== 0 || mdd !== 0

  const runInterpret = useCallback(
    async (signal?: AbortSignal) => {
      if (!hasMetrics) return
      setInterpreting(true)
      setInterpretError(null)
      try {
        const res = await apiClient.post<{ data: InterpretData }>(
          '/backtest/interpret',
          {
            symbol,
            annual_return: annualReturn,
            sharpe,
            mdd,
            leverage,
            walk_forward: walkForward
              ? {
                  is_oos_gap: walkForward.is_oos_gap,
                  robustness_ratio: walkForward.robustness_ratio,
                  overfit_risk: walkForward.overfit_risk,
                  alpha_decay: walkForward.alpha_decay,
                }
              : null,
          },
          { signal },
        )
        setInterpret(res.data)
      } catch (e: any) {
        if (e?.name === 'AbortError') return
        setInterpretError(e?.message || '解读失败')
      } finally {
        setInterpreting(false)
      }
    },
    [symbol, annualReturn, sharpe, mdd, leverage, hasMetrics, walkForward],
  )

  useEffect(() => {
    if (!ai03Enabled) return
    const ctrl = new AbortController()
    runInterpret(ctrl.signal)
    return () => ctrl.abort()
  }, [ai03Enabled, runInterpret])

  const runOverfit = async () => {
    const param_sweep = sweeps
      .map((s) => ({
        param: s.param.trim(),
        sharpe: s.sharpe
          .split(/[,\s]+/)
          .map((x) => Number(x))
          .filter((x) => !Number.isNaN(x)),
      }))
      .filter((s) => s.param && s.sharpe.length >= 2)
    if (param_sweep.length === 0) {
      setOverfit(null)
      return
    }
    try {
      const res = await apiClient.post<{ data: OverfitData }>('/backtest/overfit-check', {
        param_sweep,
      })
      setOverfit(res.data)
    } catch {
      setOverfit(null)
    }
  }

  if (!ai03Enabled) return null

  return (
    <div className="glass-card rounded-xl border border-violet-500/30 bg-violet-500/5 shadow-sm">
      <div className="flex items-center justify-between gap-2 flex-wrap border-b border-border/30 bg-secondary/20 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-violet-500" />
          <span className="text-xs font-bold uppercase tracking-wide text-violet-600 dark:text-violet-400">
            AI-03 · 回测报告解读员
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-[10px]"
          disabled={interpreting || !hasMetrics}
          onClick={() => runInterpret()}
        >
          <RefreshCw className={cn('mr-1 h-3 w-3', interpreting && 'animate-spin')} />
          重新解读
        </Button>
      </div>

      <div className="space-y-3 p-4">
        {/* 解读区 */}
        {!hasMetrics && (
          <p className="text-[11px] text-muted-foreground">暂无回测指标可解读。</p>
        )}
        {interpreting && (
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            主脑正在咀嚼回测指标...
          </div>
        )}
        {interpretError && (
          <div className="flex items-center gap-2 text-[11px] text-red-500">
            <AlertTriangle className="h-3 w-3" />
            {interpretError}
          </div>
        )}
        {interpret && !interpreting && (
          <div className="space-y-1.5">
            <p className="text-xs leading-relaxed text-foreground">{interpret.summary}</p>
            <div className="flex items-center gap-2 font-mono text-[10px]">
              <span
                className={cn(
                  'rounded px-1.5 py-0.5',
                  interpret.source === 'llm'
                    ? 'bg-violet-500/15 text-violet-500'
                    : 'bg-amber-500/15 text-amber-500',
                )}
              >
                {interpret.source === 'llm' ? 'LLM 解读' : '降级摘要'}
              </span>
              <span className="text-muted-foreground">
                置信度 {(interpret.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        )}

        {/* 过拟合检测区 */}
        <div className="space-y-2 border-t border-border/20 pt-2">
          <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
            <ShieldAlert className="h-3 w-3" />
            过拟合检测（参数敏感性 · 阈值 {0.4}）
          </div>
          <div className="space-y-1.5">
            {sweeps.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={s.param}
                  onChange={(e) =>
                    setSweeps((prev) =>
                      prev.map((p, j) => (j === i ? { ...p, param: e.target.value } : p)),
                    )
                  }
                  placeholder="参数名"
                  className="h-7 w-24 rounded border border-border/50 bg-background/60 px-2 text-[11px] outline-none focus:border-violet-500/50"
                />
                <input
                  value={s.sharpe}
                  onChange={(e) =>
                    setSweeps((prev) =>
                      prev.map((p, j) => (j === i ? { ...p, sharpe: e.target.value } : p)),
                    )
                  }
                  placeholder="夏普序列，逗号分隔 如 1.6,0.9,1.5"
                  className="h-7 flex-1 rounded border border-border/50 bg-background/60 px-2 font-mono text-[11px] outline-none focus:border-violet-500/50"
                />
                {sweeps.length > 1 && (
                  <button
                    onClick={() => setSweeps((prev) => prev.filter((_, j) => j !== i))}
                    className="px-1 text-[11px] text-red-500/70 hover:text-red-500"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-3 text-[10px]"
              onClick={() => setSweeps((p) => [...p, { param: '', sharpe: '' }])}
            >
              ＋ 参数
            </Button>
            <Button
              size="sm"
              className="h-7 bg-violet-500 px-3 text-[10px] text-white hover:bg-violet-600"
              onClick={runOverfit}
            >
              运行检测
            </Button>
            {overfit && (
              <span
                className={cn(
                  'ml-auto flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px]',
                  overfit.overfit
                    ? 'bg-red-500/15 text-red-500'
                    : 'bg-emerald-500/15 text-emerald-500',
                )}
              >
                {overfit.overfit ? (
                  <ShieldAlert className="h-3 w-3" />
                ) : (
                  <ShieldCheck className="h-3 w-3" />
                )}
                {overfit.overfit ? '疑似过拟合' : '未触发预警'} · 敏感度{' '}
                {overfit.max_sensitivity}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
