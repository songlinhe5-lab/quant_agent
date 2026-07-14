'use client'

import React from 'react'
import { Filter, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SortableTh, ScreenerRow } from './table-components'
import { getZhLabel } from './shared'
import { useScreenerContext } from './screener-context'
import { DataState, resolveDataStatus } from '@/components/data-state'
import { ScreenerAgGrid } from './screener-ag-grid'

export function ScreenerResultsTable() {
  const {
    realDataLength, columnFilters, setColumnFilters, setCurrentPage, dslQuery, fetchPageData, pageSize, sortKey, sortDir,
    handleExportCSV, isAllCurrentPageSelected, toggleAll, handleSort, dynamicCols, handleApplyFilter, handleClearFilter,
    isLoading, paginatedData, selected, toggleOne, handleAddAndOpen, handleAddSingle, setPreviewData,
    handleSendToCopilot, handleSendToBacktest, currentPage, totalPages, setPageSize, setSelected, handleAddBatch
  } = useScreenerContext()

  const viewStatus = resolveDataStatus({
    loading: isLoading,
    empty: !isLoading && paginatedData.length === 0,
  })
  const useAgGrid = pageSize >= 50 && paginatedData.length > 0

  return (
    <div className="glass-card rounded-xl overflow-hidden transition-colors duration-base border border-border/40 shadow-sm relative flex flex-col h-[500px]">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between bg-secondary/30 shrink-0">
        <div className="flex items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            筛选结果
            <span className="ml-2 bg-primary/10 text-primary px-1.5 py-0.5 rounded-md font-mono">{realDataLength}</span>
          </span>
          {useAgGrid && (
            <span className="text-[10px] text-muted-foreground font-mono">AG Grid</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {Object.keys(columnFilters).length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => { setColumnFilters({}); setCurrentPage(1); if (dslQuery) fetchPageData(dslQuery, 1, pageSize, sortKey, sortDir, {}); }} className="h-7 text-[10px] text-amber-600 dark:text-amber-500 hover:text-amber-700 bg-amber-500/10">清除全部过滤</Button>
          )}
          <Button variant="ghost" size="sm" onClick={handleExportCSV} className="h-7 text-[10px] text-muted-foreground hover:text-foreground">导出 CSV</Button>
        </div>
      </div>

      {useAgGrid ? (
        <div className="flex-1 min-h-0">
          <ScreenerAgGrid
            rows={paginatedData as Record<string, unknown>[]}
            dynamicCols={dynamicCols}
            selected={selected}
            onToggleOne={toggleOne}
            onPreview={setPreviewData}
          />
        </div>
      ) : (
      <DataState
        status={viewStatus}
        skeletonRows={8}
        emptyTitle={dslQuery ? '未能匹配到标的' : '开始选股'}
        emptyDescription={dslQuery ? '请尝试放宽筛选条件' : '在上方输入自然语言，或点击灵感快捷键开始选股'}
        className="flex-1"
      >
      <div className="overflow-auto flex-1 custom-scrollbar h-full">
        <table className="w-full text-xs" role="table" aria-label="选股结果数据网格">
          <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
            <tr className="border-b border-border/40">
              <th scope="col" className="w-10 px-3 py-2 pl-4"><input type="checkbox" className="rounded-sm border-border accent-primary focus:ring-primary/30" checked={isAllCurrentPageSelected} onChange={(e) => toggleAll(e.target.checked)} aria-label="全选本页" /></th>
              <SortableTh label="#" k="rank" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="left" className="w-12" />
              <SortableTh label="代码" k="symbol" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="left" className="min-w-[120px]" />
              <SortableTh label="名称" k="name" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="left" className="min-w-[160px]" />
              {dynamicCols.map(col => (<SortableTh key={col} label={getZhLabel(col)} k={col} sortKey={sortKey} sortDir={sortDir} onSort={handleSort} filterRange={columnFilters[col]} onApplyFilter={(r) => handleApplyFilter(col, r)} onClearFilter={() => handleClearFilter(col)} />))}
              <th scope="col" className="min-w-[110px] px-3 py-2 pr-4 text-right text-muted-foreground font-medium whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/15">
            {paginatedData.map((r) => (
              <ScreenerRow key={r.symbol} r={r} isSelected={selected.includes(r.symbol)} dynamicCols={dynamicCols} toggleOne={toggleOne} handleAddAndOpen={handleAddAndOpen} handleAddSingle={handleAddSingle} onPreview={setPreviewData} onSendToCopilot={handleSendToCopilot} onSendToBacktest={handleSendToBacktest} />
            ))}
          </tbody>
        </table>
      </div>
      </DataState>
      )}

      {paginatedData.length > 0 && (
        <div className="px-4 py-2.5 border-t border-border/30 bg-secondary/10 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>每页显示</span>
            <select value={pageSize} onChange={(e) => { const newSize = Number(e.target.value); setPageSize(newSize); setCurrentPage(1); if (dslQuery) fetchPageData(dslQuery, 1, newSize, sortKey, sortDir, columnFilters); }} className="bg-background border border-border/50 rounded px-1.5 py-0.5 outline-none focus:ring-1 focus:ring-primary transition-all cursor-pointer text-foreground">
              <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
            </select>
            <span>条</span>
          </div>
          <div className="flex items-center gap-4 text-[11px]">
            <div className="flex items-center gap-3">
              <span className="text-muted-foreground font-mono">{currentPage} / {totalPages || 1} 页 (共 {realDataLength} 只标的)</span>
              <div className="flex items-center gap-1.5 border-l border-border/40 pl-3">
                <span className="text-muted-foreground">跳至</span>
                <input type="number" min={1} max={totalPages || 1} placeholder={currentPage.toString()} title="输入页码后按回车跳转" className="w-12 h-6 bg-background border border-border/50 rounded text-center outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-all tabular-nums text-foreground disabled:opacity-50" disabled={isLoading || totalPages <= 1} onKeyDown={(e) => { if (e.key === 'Enter') { let val = parseInt(e.currentTarget.value); if (!isNaN(val)) { val = Math.max(1, Math.min(totalPages || 1, val)); if (val !== currentPage) { setCurrentPage(val); if (dslQuery) fetchPageData(dslQuery, val, pageSize, sortKey, sortDir, columnFilters); } } e.currentTarget.value = ''; e.currentTarget.blur(); } }} />
                <span className="text-muted-foreground">页</span>
              </div>
            </div>
            <div className="flex gap-1.5">
              <Button variant="outline" size="sm" className="h-6 px-2.5 text-[10px]" onClick={() => { const newPage = Math.max(1, currentPage - 1); setCurrentPage(newPage); if (dslQuery) fetchPageData(dslQuery, newPage, pageSize, sortKey, sortDir, columnFilters); }} disabled={currentPage === 1 || isLoading}>上一页</Button>
              <Button variant="outline" size="sm" className="h-6 px-2.5 text-[10px]" onClick={() => { const newPage = Math.min(totalPages, currentPage + 1); setCurrentPage(newPage); if (dslQuery) fetchPageData(dslQuery, newPage, pageSize, sortKey, sortDir, columnFilters); }} disabled={currentPage === totalPages || totalPages === 0 || isLoading}>下一页</Button>
            </div>
          </div>
        </div>
      )}

      {selected.length > 0 && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center justify-between bg-card dark:bg-zinc-900 border border-border shadow-xl rounded-full px-4 py-2.5 animate-in slide-in-from-bottom-5 fade-in duration-300 z-20">
          <div className="flex items-center gap-4">
            <span className="text-xs font-medium">已选中 <span className="font-bold text-primary font-mono bg-primary/10 px-1.5 py-0.5 rounded">{selected.length}</span> 只标的</span>
            <div className="h-4 w-px bg-border" />
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" className="text-xs h-7 gap-1.5 rounded-full" onClick={() => setSelected([])}>取消选择</Button>
              <Button size="sm" className="text-xs h-7 gap-1.5 rounded-full shadow-sm" onClick={handleAddBatch}><Plus className="h-3.5 w-3.5" aria-hidden="true" /> 批量推入 Watchlist</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}