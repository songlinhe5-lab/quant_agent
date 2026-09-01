'use client'

/**
 * FIN-07 · 重述 diff（docs/28 §七）：首次披露 vs 最新，差异标红。
 * AG Grid 虚拟滚动（行数可能上千：全部科目 × 全部申报）。
 */

import { useEffect, useRef } from 'react'
import { AllCommunityModule, ModuleRegistry, createGrid, type ColDef, type GridApi } from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { DataSourceBadge } from '@/components/ui/data-display/DataSourceBadge'
import { FINANCIALS_PATHS, type RestatementItem } from './api'
import { useFinancialsData } from './use-financials-data'

ModuleRegistry.registerModules([AllCommunityModule])

interface RestatementsResponse {
  items: RestatementItem[]
  count: number
}

function fmt(v: number | null | undefined): string {
  return v === null || v === undefined ? '--' : Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v.toLocaleString()
}

export function RestatementDiff({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<RestatementsResponse>(FINANCIALS_PATHS.restatements(entity))
  const hostRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<GridApi | null>(null)

  useEffect(() => {
    if (!hostRef.current || !data) return
    const cols: ColDef[] = [
      { headerName: '科目', field: 'label', pinned: 'left', width: 150 },
      { headerName: '期间末', field: 'period_end', width: 110 },
      { headerName: '首次披露', field: 'value_as_reported', width: 130, valueFormatter: (p) => fmt(p.value) },
      { headerName: '最新', field: 'value_latest', width: 130, valueFormatter: (p) => fmt(p.value) },
      { headerName: '绝对差', field: 'delta', width: 120, valueFormatter: (p) => fmt(p.value) },
      {
        headerName: '相对差',
        field: 'delta_pct',
        width: 110,
        valueFormatter: (p) => (p.value === null ? '--' : `${(p.value * 100).toFixed(2)}%`),
        cellClass: (p) => (p.value ? 'text-red-400' : ''),
      },
      { headerName: '首披日', field: 'filed_as_reported', width: 110 },
      { headerName: '重述日', field: 'filed_latest', width: 110 },
    ]
    gridRef.current = createGrid(hostRef.current, {
      columnDefs: cols,
      rowData: data.items,
      theme: 'legacy',
      defaultColDef: { sortable: true },
    })
    return () => {
      gridRef.current?.destroy()
      gridRef.current = null
    }
  }, [data])

  if (error) return <EmptyState title="重述数据加载失败" description={error} />
  if (!data)
    return <EmptyState title={loading ? '加载中…' : '无重述记录'} description="该实体暂无重述事实——好消息" />

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">重述科目 {data.count} 条 · 相对差非零标红</span>
        <DataSourceBadge source="sec-edgar" />
      </div>
      <div ref={hostRef} className="ag-theme-quartz-dark h-[360px] w-full" data-testid="restatement-grid" />
    </div>
  )
}

export default RestatementDiff
