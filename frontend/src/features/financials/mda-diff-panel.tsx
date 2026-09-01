'use client'

/**
 * FIN-08c · MD&A / 风险因素 YoY diff（docs/28 §5.3，Lazy Prices 依据）：
 * 重写章节排前，词级变化片段 old 删红 / new 增绿。章节名保持后端原文（检索键）。
 */

import { FileWarning } from 'lucide-react'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { DataSourceBadge } from '@/components/ui/data-display/DataSourceBadge'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type TextDiffSection, type TextDiffView } from './api'
import { useFinancialsData } from './use-financials-data'

const SECTION_LABELS: Record<string, string> = {
  risk_factors: '风险因素 (Item 1A)',
  mda: '管理层讨论 (Item 7)',
  quantitative_qualitative: '市场风险定量披露 (Item 7A)',
}

const STATUS_STYLE: Record<TextDiffSection['status'], string> = {
  rewritten: 'bg-amber-500/15 text-amber-500',
  similar: 'bg-emerald-500/15 text-emerald-400',
  missing: 'bg-gray-800 text-gray-500',
}

const STATUS_TEXT: Record<TextDiffSection['status'], string> = {
  rewritten: '措辞重写',
  similar: '基本不变',
  missing: '单侧缺失',
}

function Fragments({ section }: { section: TextDiffSection }) {
  if (section.status !== 'rewritten' || !section.fragments?.length) return null
  return (
    <ul className="mt-1 space-y-1 text-xs">
      {section.fragments.map((f, i) => (
        <li key={i} className="space-y-0.5 border-l-2 border-gray-700 pl-2">
          {f.old && <p className="text-red-400 line-through decoration-red-400/40">- {f.old}</p>}
          {f.new && <p className="text-emerald-400">+ {f.new}</p>}
        </li>
      ))}
    </ul>
  )
}

export function MdaDiffPanel({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<TextDiffView>(FINANCIALS_PATHS.textDiff(entity))

  if (error) return <EmptyState title="文本 diff 加载失败" description={error} />
  if (!data)
    return <EmptyState title={loading ? '加载中…' : '暂无数据'} description="需要至少两份含原文的 10-K" />

  return (
    <div className="space-y-3" data-testid="mda-diff">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-gray-400">
          FY{data.old.fiscal_year ?? '?'} → FY{data.new.fiscal_year ?? '?'}（{data.old.accession_no} vs{' '}
          {data.new.accession_no}）
        </span>
        <DataSourceBadge source="sec-edgar" />
        {data.rewritten.length > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 text-amber-500">
            <FileWarning className="size-3.5" /> 重写章节：{data.rewritten.join('、')}
          </span>
        )}
      </div>

      {data.sections.map((s) => (
        <div key={s.section} className="rounded border border-gray-800 bg-gray-900/60 p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-gray-200">{SECTION_LABELS[s.section] ?? s.section}</span>
            <span className={cn('rounded px-1.5 text-[10px] leading-4', STATUS_STYLE[s.status])}>
              {STATUS_TEXT[s.status]}
            </span>
            {s.similarity !== undefined && (
              <span className="text-xs text-gray-500">相似度 {(s.similarity * 100).toFixed(1)}%</span>
            )}
            {s.missing_in && (
              <span className="text-xs text-gray-500">
                {s.missing_in === 'new' ? '新年报缺失' : '旧年报缺失'}
              </span>
            )}
          </div>
          <Fragments section={s} />
        </div>
      ))}
    </div>
  )
}

export default MdaDiffPanel
