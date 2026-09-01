'use client'

/**
 * FIN-07 · 多期报表 AG Grid（docs/28 §七）
 * 行=科目、列=期间；common-size 切换、口径切换；勾稽失败标红、推导值浅色角标。
 */

import { useEffect, useRef, useState } from 'react'
import { AllCommunityModule, ModuleRegistry, createGrid, type ColDef, type GridApi } from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { DataSourceBadge } from '@/components/ui/data-display/DataSourceBadge'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type StatementBasis, type StatementKind, type StatementRow, type StatementView } from './api'
import { useFinancialsData } from './use-financials-data'

ModuleRegistry.registerModules([AllCommunityModule])

const STATEMENTS: { id: StatementKind; label: string }[] = [
  { id: 'income', label: '利润表' },
  { id: 'balance', label: '资产负债表' },
  { id: 'cash', label: '现金流量表' },
]
const BASES: { id: StatementBasis; label: string }[] = [
  { id: 'latest', label: '最新口径' },
  { id: 'as_reported', label: '首次披露' },
]

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      data-slot={label}
      onClick={onClick}
      className={cn('rounded px-2 py-1 text-xs border', on ? 'bg-violet-500/20 text-violet-300 border-violet-500/40' : 'text-gray-400 border-gray-700')}
    >
      {label}
    </button>
  )
}

export function StatementGrid({ entity }: { entity: string }) {
  const [kind, setKind] = useState<StatementKind>('income')
  const [basis, setBasis] = useState<StatementBasis>('latest')
  const [useCommonSize, setUseCommonSize] = useState(false)
  const { data, loading, error } = useFinancialsData<StatementView>(FINANCIALS_PATHS.statements(entity), {
    statement: kind,
    basis,
  })
  const hostRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<GridApi | null>(null)

  useEffect(() => {
    if (!hostRef.current || !data) return
    const cols: ColDef[] = [
      { headerName: '科目', field: 'label', pinned: 'left', width: 160 },
      ...data.periods.map((p, i) => ({
        headerName: p,
        field: `c${i}`,
        width: 130,
        cellClass: (ctx: { data: StatementRow }) =>
          ctx.data.check_failed[i]?.length ? 'text-red-400' : ctx.data.restated[i] ? 'text-amber-300' : '',
      })),
    ]
    const rowData = data.rows.map((r) => {
      const series = useCommonSize ? r.common_size : r.values
      const row: Record<string, unknown> = { label: r.label, concept: r.concept }
      data.periods.forEach((_, i) => {
        row[`c${i}`] = series[i]
      })
      return row
    })
    gridRef.current = createGrid(hostRef.current, { columnDefs: cols, rowData, theme: 'legacy' })
    return () => {
      gridRef.current?.destroy()
      gridRef.current = null
    }
  }, [data, useCommonSize])

  if (error) return <EmptyState title="报表加载失败" description={error} />
  if (!data) return <EmptyState title={loading ? '加载中…' : `${entity} 无 ${kind} 报表`} description="请先回填该实体的财报事实" />

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        {STATEMENTS.map((s) => (
          <Chip key={s.id} label={s.label} on={kind === s.id} onClick={() => setKind(s.id)} />
        ))}
        <span className="text-gray-600">|</span>
        {BASES.map((b) => (
          <Chip key={b.id} label={b.label} on={basis === b.id} onClick={() => setBasis(b.id)} />
        ))}
        <Chip label="Common-size" on={useCommonSize} onClick={() => setUseCommonSize((v) => !v)} />
        <span className="ml-auto flex items-center gap-2">
          {data.integrity.failed_periods.length > 0 && (
            <span className="text-red-400">勾稽失败: {data.integrity.failed_periods.join(', ')}</span>
          )}
          <DataSourceBadge source={Object.keys(data.source_mix).join('/')} />
          <span className="text-gray-500">{data.currency}</span>
        </span>
      </div>
      <div ref={hostRef} className="ag-theme-quartz-dark h-[420px] w-full" data-testid="statement-grid" />
    </div>
  )
}

export default StatementGrid
