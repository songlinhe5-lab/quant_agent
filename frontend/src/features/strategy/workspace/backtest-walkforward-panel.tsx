'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api-client'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'

interface WfInterpretData {
  is_oos_gap: number
  alpha_decay: boolean
  overfit_risk: boolean
  robustness_ratio: number
  oos_sharpe_mean: number
  is_sharpe_mean: number
  drift_reasons: string[]
  summary: string
  source: string
}

interface BacktestWalkForwardPanelProps {
  ticker: string
  period: string
  params?: Record<string, any>
}

/**
 * AI-03 增强 · Walk-Forward 过拟合 / Alpha 衰减检测面板。
 * 受 AI-09 推送偏好底座 `ai03` 开关统一管控。
 * 流程：真实跑 /backtest/walk-forward → 喂给 /backtest/interpret/walk-forward，
 * 把过拟合风险 + Alpha 衰减徽标挂到回测页 Tear Sheet。
 */
export function BacktestWalkForwardPanel({
  ticker,
  period,
  params,
}: BacktestWalkForwardPanelProps) {
  const ai03Enabled = useAiPushPrefStore((s) => s.isEnabled('ai03'))

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<WfInterpretData | null>(null)

  const run = async () => {
    if (!ticker) return
    setLoading(true)
    setError(null)
    try {
      const wf = await apiClient.post<{ data: Record<string, any> }>(
        '/backtest/walk-forward',
        {
          ticker,
          period,
          strategy_key: 'sma_cross',
          params: params || {},
        },
      )
      const report = wf.data
      const res = await apiClient.post<{ data: WfInterpretData }>(
        '/backtest/interpret/walk-forward',
        { report, use_llm: true },
      )
      setData(res.data)
    } catch (e: any) {
      setError(e?.message || 'Walk-Forward 检测失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  if (!ai03Enabled) return null

  return (
    <div className="glass-card rounded-xl border border-violet-500/30 bg-violet-500/5 shadow-sm">
      <div className="flex items-center justify-between gap-2 flex-wrap border-b border-border/30 bg-secondary/20 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-violet-500" />
          <span className="text-xs font-bold uppercase tracking-wide text-violet-600 dark:text-violet-400">
            AI-03 · Walk-Forward 过拟合 / Alpha 衰减
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-[10px]"
          disabled={loading || !ticker}
          onClick={run}
        >
          <ShieldAlert className={cn('mr-1 h-3 w-3', loading && 'animate-spin')} />
          {loading ? '滚动验证中...' : '运行检测'}
        </Button>
      </div>

      <div className="space-y-3 p-4">
        {!ticker && (
          <p className="text-[11px] text-muted-foreground">尚无标的，先跑一次回测。</p>
        )}
        {loading && (
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            主脑正在跨窗口滚动验证 IS/OOS 漂移...
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 text-[11px] text-red-500">
            <AlertTriangle className="h-3 w-3" />
            {error}
          </div>
        )}
        {data && !loading && (
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={cn(
                  'flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]',
                  data.overfit_risk
                    ? 'bg-red-500/15 text-red-500'
                    : 'bg-emerald-500/15 text-emerald-500',
                )}
              >
                {data.overfit_risk ? (
                  <ShieldAlert className="h-3 w-3" />
                ) : (
                  <ShieldCheck className="h-3 w-3" />
                )}
                {data.overfit_risk ? '过拟合风险' : '过拟合可控'}
              </span>
              <span
                className={cn(
                  'flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]',
                  data.alpha_decay
                    ? 'bg-amber-500/15 text-amber-500'
                    : 'bg-emerald-500/15 text-emerald-500',
                )}
              >
                <TrendingDown className="h-3 w-3" />
                {data.alpha_decay ? 'Alpha 衰减' : 'Alpha 稳健'}
              </span>
              <span className="rounded bg-secondary/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                IS/OOS 缺口 {data.is_oos_gap}
              </span>
              <span className="rounded bg-secondary/40 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                OOS 盈利折 {(data.robustness_ratio * 100).toFixed(0)}%
              </span>
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 font-mono text-[10px]',
                  data.source === 'llm'
                    ? 'bg-violet-500/15 text-violet-500'
                    : 'bg-amber-500/15 text-amber-500',
                )}
              >
                {data.source === 'llm' ? 'LLM 解读' : '降级摘要'}
              </span>
            </div>

            <p className="text-xs leading-relaxed text-foreground">{data.summary}</p>

            {data.drift_reasons?.length > 0 && (
              <div className="rounded border border-border/20 bg-background/40 p-2">
                <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
                  漂移原因
                </p>
                <ul className="space-y-0.5 text-[10px] text-muted-foreground">
                  {data.drift_reasons.map((r, i) => (
                    <li key={i}>· {r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
