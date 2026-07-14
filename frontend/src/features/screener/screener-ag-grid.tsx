'use client'

import { useEffect, useRef } from 'react'
import {
  AllCommunityModule,
  ModuleRegistry,
  createGrid,
  type ColDef,
  type GridApi,
} from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'
import { formatDisplaySymbol, getZhLabel } from './shared'

ModuleRegistry.registerModules([AllCommunityModule])

type ScreenerAgGridProps = {
  rows: Record<string, unknown>[]
  dynamicCols: string[]
  selected: string[]
  onToggleOne: (symbol: string, checked: boolean) => void
  onPreview: (payload: { symbol: string; price?: number; change?: number }) => void
}

/**
 * FE-13: 选股结果 AG Grid 虚拟滚动（pageSize ≥ 50 时启用）
 */
export function ScreenerAgGrid({
  rows,
  dynamicCols,
  selected,
  onToggleOne,
  onPreview,
}: ScreenerAgGridProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<GridApi | null>(null)
  const selectedRef = useRef(selected)
  selectedRef.current = selected

  useEffect(() => {
    if (!hostRef.current) return

    const colDefs: ColDef[] = [
      {
        headerName: '',
        field: '_sel',
        width: 44,
        pinned: 'left',
      },
      { headerName: '#', field: 'rank', width: 64, pinned: 'left' },
      {
        headerName: '代码',
        field: 'symbol',
        width: 120,
        pinned: 'left',
        cellRenderer: (p: { value: string }) => formatDisplaySymbol(p.value),
        onCellClicked: (e) => {
          const symbol = String(e.data?.symbol ?? '')
          if (!symbol) return
          onPreview({
            symbol,
            price: typeof e.data?.price === 'number' ? e.data.price : undefined,
            change: typeof e.data?.chg === 'number' ? e.data.chg : undefined,
          })
        },
      },
      { headerName: '名称', field: 'name', flex: 1, minWidth: 140 },
      ...dynamicCols.map((col) => ({
        headerName: getZhLabel(col),
        field: col,
        width: 110,
        valueFormatter: (p: { value: unknown }) =>
          typeof p.value === 'number' ? p.value.toLocaleString() : String(p.value ?? '—'),
      })),
    ]

    const api = createGrid(hostRef.current, {
      columnDefs: colDefs,
      rowData: rows,
      rowSelection: {
        mode: 'multiRow',
        checkboxes: true,
        headerCheckbox: true,
        enableClickSelection: false,
      },
      getRowId: (p) => String(p.data.symbol),
      animateRows: false,
      rowHeight: 36,
      headerHeight: 36,
      onSelectionChanged: () => {
        const selectedNodes = api.getSelectedRows() as { symbol: string }[]
        const next = new Set(selectedNodes.map((r) => r.symbol))
        const prev = new Set(selectedRef.current)
        for (const s of next) {
          if (!prev.has(s)) onToggleOne(s, true)
        }
        for (const s of prev) {
          if (!next.has(s)) onToggleOne(s, false)
        }
      },
      defaultColDef: {
        sortable: true,
        resizable: true,
        suppressMovable: true,
      },
    })
    apiRef.current = api

    return () => {
      api.destroy()
      apiRef.current = null
    }
    // 仅挂载时建表；数据变更用下方 effect 同步
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const api = apiRef.current
    if (!api) return
    api.setGridOption('rowData', rows)
    api.forEachNode((node) => {
      const sym = String(node.data?.symbol ?? '')
      node.setSelected(selected.includes(sym), false)
    })
  }, [rows, selected])

  useEffect(() => {
    const api = apiRef.current
    if (!api) return
    const dynamic: ColDef[] = dynamicCols.map((col) => ({
      headerName: getZhLabel(col),
      field: col,
      width: 110,
    }))
    const base = (api.getColumnDefs() ?? []).filter(
      (c) => !dynamicCols.includes(String((c as ColDef).field ?? '')),
    )
    // 保留固定列，刷新动态列
    const fixed = base.filter((c) =>
      ['_sel', 'rank', 'symbol', 'name'].includes(String((c as ColDef).field)),
    )
    api.setGridOption('columnDefs', [...fixed, ...dynamic])
  }, [dynamicCols])

  return (
    <div
      ref={hostRef}
      className="ag-theme-quartz w-full h-full min-h-[360px] dark:[color-scheme:dark]"
      data-testid="screener-ag-grid"
    />
  )
}
