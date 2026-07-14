/**
 * PT-02b: 漂移面板 (TE / 累计偏离 / 信号一致率)
 */
'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'

interface DriftAlert {
  te: number
  threshold: number
  ts: string
}

interface CompareData {
  tracking_error: number
  cumulative_drift: number
  paper_sharpe: number
  paper_max_dd: number
}

interface DriftPanelProps {
  portfolioId: string
}

const TE_THRESHOLD = 0.15
const DRIFT_THRESHOLD = 0.10

export function DriftPanel({ portfolioId }: DriftPanelProps) {
  const [compareData, setCompareData] = useState<CompareData | null>(null)
  const [driftAlert, setDriftAlert] = useState<DriftAlert | null>(null)

  useEffect(() => {
    apiClient
      .get<any>(`/paper/portfolios/${portfolioId}/compare`, { days: 30 })
      .then((res) => setCompareData(res.data?.data || null))
      .catch(() => {})
  }, [portfolioId])

  const te = compareData?.tracking_error ?? 0
  const drift = compareData?.cumulative_drift ?? 0
  const teExceeded = te > TE_THRESHOLD
  const driftExceeded = Math.abs(drift) > DRIFT_THRESHOLD
  const hasAlert = teExceeded || driftExceeded

  return (
    <div className="space-y-3">
      {/* Alert Banner */}
      {hasAlert && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-500 text-xs">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>
            纸面漂移告警：
            {teExceeded && `TE ${(te * 100).toFixed(1)}% 超过阈值 ${(TE_THRESHOLD * 100).toFixed(0)}%`}
            {teExceeded && driftExceeded && ' · '}
            {driftExceeded && `累计偏离 ${(drift * 100).toFixed(1)}pp 超过阈值 ${(DRIFT_THRESHOLD * 100).toFixed(0)}pp`}
          </span>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className={cn('rounded-lg border p-3', teExceeded ? 'border-red-500/50' : 'border-border')}>
          <p className="text-xs text-muted-foreground">跟踪误差 (TE)</p>
          <p className={cn('text-lg font-bold font-mono', teExceeded ? 'text-red-500' : '')}>
            {(te * 100).toFixed(1)}%
          </p>
          <p className="text-xs text-muted-foreground">年化</p>
        </div>
        <div className={cn('rounded-lg border p-3', driftExceeded ? 'border-red-500/50' : 'border-border')}>
          <p className="text-xs text-muted-foreground">累计偏离</p>
          <p className={cn('text-lg font-bold font-mono', driftExceeded ? 'text-red-500' : '')}>
            {(drift * 100).toFixed(1)}pp
          </p>
          <p className="text-xs text-muted-foreground">百分点</p>
        </div>
        <div className="rounded-lg border border-border p-3">
          <p className="text-xs text-muted-foreground">最大回撤</p>
          <p className="text-lg font-bold font-mono">
            {((compareData?.paper_max_dd ?? 0) * 100).toFixed(1)}%
          </p>
          <p className="text-xs text-muted-foreground">历史</p>
        </div>
      </div>
    </div>
  )
}
