'use client'

/**
 * FIN-07 · 同业分位（docs/28 §七）：frames 截面分位 + 行业聚合。
 *
 * 后端（FIN-06）只回聚合（中位数/四分位/分位），不给同业明细行——散点图无数据支撑，
 * 先以「本体在 p25~p75 区间中的位置」呈现；后端补截面明细后再升级为散点。
 */

import { useState } from 'react'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { DataSourceBadge } from '@/components/ui/data-display/DataSourceBadge'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type PeersResponse } from './api'
import { PeerScatter } from './peer-scatter'
import { useFinancialsData } from './use-financials-data'

const CONCEPTS = ['revenue', 'net_income', 'total_assets'] as const

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Math.abs(v) >= 1e8 ? `${(v / 1e8).toFixed(1)}亿` : Math.abs(v) >= 1e4 ? `${(v / 1e4).toFixed(1)}万` : v.toLocaleString()
}

export function PeerCompare({ entity }: { entity: string }) {
  const [concept, setConcept] = useState<string>('revenue')
  const [peerSet, setPeerSet] = useState('')
  const { data, loading, error } = useFinancialsData<PeersResponse>(FINANCIALS_PATHS.peers(entity), {
    concept,
    ...(peerSet.trim() ? { peer_set: peerSet.trim() } : {}),
  })

  if (error) return <EmptyState title="同业数据加载失败" description={error} />
  if (!data) return <EmptyState title={loading ? '加载中…' : '无同业数据'} description="请先回填本体与同业的可比期间事实" />

  const { value, percentile, aggregates, sample_size, insufficient } = data
  const lo = aggregates.p25 ?? 0
  const hi = aggregates.p75 ?? 0
  // 视口：p25~p75 带上下各留 30% 边距，保证极端值也在条内
  const pad = (hi - lo || Math.abs(value) || 1) * 0.3
  const vMin = lo - pad
  const vMax = hi + pad
  const scalePos = (v: number) => Math.max(0, Math.min(100, ((v - vMin) / (vMax - vMin || 1)) * 100))

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {CONCEPTS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setConcept(c)}
            className={cn('rounded border px-2 py-1', concept === c ? 'border-violet-500/40 text-violet-300' : 'border-gray-700 text-gray-400')}
          >
            {c}
          </button>
        ))}
        <input
          value={peerSet}
          onChange={(e) => setPeerSet(e.target.value)}
          placeholder="peer_set（逗号分隔，留空=全市场截面）"
          className="w-64 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200"
        />
        <span className="ml-auto flex items-center gap-2">
          <span className="text-gray-500">
            {data.basis === 'peers' ? '手工同业' : '全市场'} · 帧 {data.frame} · {data.tag}
          </span>
          <DataSourceBadge source="sec-edgar" />
        </span>
      </div>

      {insufficient ? (
        <EmptyState
          title="同业样本不足"
          description={`仅 ${sample_size} 家（< 8），禁止出分位结论——不是没算，是不能算`}
        />
      ) : (
        <>
          <div className="flex items-end gap-4">
            <div>
              <p className="text-xs text-gray-500">本体 {entity}</p>
              <p className="text-2xl font-semibold text-emerald-400">{fmt(value)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">截面分位</p>
              <p className="text-2xl font-semibold text-violet-300">{percentile!.toFixed(1)}%</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">样本</p>
              <p className="text-2xl font-semibold text-gray-200">{sample_size}</p>
            </div>
          </div>

          {/* FIN-09：有明细行 → 散点（本体高亮）；否则退回区间条 */}
          {data.peer_rows && data.peer_rows.length > 0 ? (
            <PeerScatter data={data} />
          ) : (
            <div className="relative h-6 rounded bg-gray-800" data-testid="peer-band">
              <div
                className="absolute h-6 rounded bg-gray-700"
                style={{ left: `${scalePos(lo)}%`, width: `${scalePos(hi) - scalePos(lo)}%` }}
              />
              <div
                className="absolute top-[-4px] h-8 w-1 rounded bg-emerald-400"
                style={{ left: `${scalePos(value)}%` }}
                title={`本体 ${fmt(value)}`}
              />
            </div>
          )}
          <div className="flex gap-6 text-xs text-gray-400">
            <span>p25 {fmt(aggregates.p25)}</span>
            <span>中位数 {fmt(aggregates.median)}</span>
            <span>p75 {fmt(aggregates.p75)}</span>
            {aggregates.revenue_weighted !== undefined && <span>收入加权 {fmt(aggregates.revenue_weighted)}</span>}
          </div>
        </>
      )}
      {data.missing_peers.length > 0 && (
        <p className="text-xs text-amber-400">缺席同业（如实报告）：{data.missing_peers.join(', ')}</p>
      )}
    </div>
  )
}

export default PeerCompare
