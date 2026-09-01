'use client'

/**
 * FIN-07 · 质量记分卡（docs/28 §七）：Piotroski F / Altman Z / Beneish M。
 * 纯 DOM，三分全部展示分项与阈值（禁黑箱总分，AGENTS §28 契约）。
 */

import { AlertTriangle, CheckCircle2, CircleDashed } from 'lucide-react'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type AnalyticsView } from './api'
import { useFinancialsData } from './use-financials-data'

function Ratio({ label, value, digits = 2 }: { label: string; value: number | null; digits?: number }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200">{value === null ? '--' : value.toFixed(digits)}</span>
    </div>
  )
}

function MissingList({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return <p className="mt-1 text-[11px] text-amber-400">缺失科目（不补零）：{items.join(', ')}</p>
}

export function QualityScorecard({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<AnalyticsView>(FINANCIALS_PATHS.analytics(entity))

  if (error) return <EmptyState title="质量分加载失败" description={error} />
  if (!data) return <EmptyState title={loading ? '加载中…' : '无质量分数据'} description="需该实体至少两期年报事实" />

  const { piotroski, altman_z, beneish_m, cash_flow_quality: cfq } = data
  const zoneTone =
    altman_z.zone === 'safe' ? 'text-emerald-400' : altman_z.zone === 'grey' ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="quality-scorecard">
      {/* Piotroski F */}
      <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
        <div className="flex items-baseline justify-between">
          <h4 className="text-sm font-medium text-gray-200">Piotroski F-Score</h4>
          <span className="text-2xl font-semibold text-emerald-400">
            {piotroski.score}
            <span className="text-sm text-gray-500">/{piotroski.max_score}</span>
          </span>
        </div>
        <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
          {piotroski.items.map((it) => (
            <li key={it.key} className="flex items-center gap-1.5 text-xs">
              {it.passed === null ? (
                <CircleDashed className="size-3.5 text-gray-600" />
              ) : it.passed ? (
                <CheckCircle2 className="size-3.5 text-emerald-400" />
              ) : (
                <AlertTriangle className="size-3.5 text-red-400" />
              )}
              <span className={cn(it.passed === null && 'text-gray-600')}>{it.name}</span>
            </li>
          ))}
        </ul>
        {piotroski.unknown.length > 0 && (
          <p className="mt-1 text-[11px] text-gray-500">无法判定（不计分）：{piotroski.unknown.join(', ')}</p>
        )}
        <MissingList items={piotroski.missing} />
      </div>

      {/* Altman Z + Beneish M + 现金流质量 */}
      <div className="space-y-3">
        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
          <div className="flex items-baseline justify-between">
            <h4 className="text-sm font-medium text-gray-200">Altman Z（破产风险）</h4>
            <span className={cn('text-2xl font-semibold', zoneTone)}>
              {altman_z.z === null ? '--' : altman_z.z.toFixed(2)}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            区域：<span className={zoneTone}>{altman_z.zone}</span> · 阈值 safe {altman_z.thresholds.safe} / grey{' '}
            {altman_z.thresholds.grey}
          </p>
          <div className="mt-2 space-y-0.5">
            {Object.entries(altman_z.components).map(([k, v]) => (
              <Ratio key={k} label={`${k} × ${altman_z.weights[k]}`} value={v} />
            ))}
          </div>
          <MissingList items={altman_z.missing} />
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
          <div className="flex items-baseline justify-between">
            <h4 className="text-sm font-medium text-gray-200">Beneish M（操纵嫌疑）</h4>
            <span className={cn('text-xl font-semibold', beneish_m.flagged ? 'text-red-400' : 'text-emerald-400')}>
              {beneish_m.m === null ? '--' : beneish_m.m.toFixed(2)}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {beneish_m.flagged === null
              ? '指数不全，无法判定'
              : beneish_m.flagged
                ? '超过阈值，存在操纵嫌疑（红）'
                : '未超阈值'}
            {' '}· 阈值 {beneish_m.threshold}
          </p>
          <MissingList items={beneish_m.missing} />
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
          <h4 className="text-sm font-medium text-gray-200">现金流质量（{cfq.asset_base === 'ending' ? '期末' : '均值'}资产）</h4>
          <div className="mt-2 space-y-0.5">
            <Ratio label="CFO / 净利润（含金量）" value={cfq.cfo_to_net_income} />
            <Ratio label="应计比率" value={cfq.accruals_ratio} />
            <Ratio label="FCF / 净利润" value={cfq.fcf_to_net_income} />
            <Ratio label="FCF 利润率" value={cfq.fcf_margin} />
            <Ratio label="资本开支强度" value={cfq.capex_intensity} />
          </div>
          <MissingList items={cfq.missing} />
        </div>
      </div>
    </div>
  )
}

export default QualityScorecard
