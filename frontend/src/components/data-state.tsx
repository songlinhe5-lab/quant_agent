'use client'

import { Inbox } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription } from '@/components/ui/empty'
import { cn } from '@/lib/utils'

export type DataViewStatus = 'loading' | 'ready' | 'stale' | 'empty'

type DataStateProps = {
  status: DataViewStatus
  /** loading 骨架行数 */
  skeletonRows?: number
  emptyTitle?: string
  emptyDescription?: string
  className?: string
  children: React.ReactNode
}

/**
 * FE-11: Skeleton → 真实数据 / STALE overlay / Empty State
 */
export function DataState({
  status,
  skeletonRows = 6,
  emptyTitle = '暂无数据',
  emptyDescription = '稍后再试或调整筛选条件',
  className,
  children,
}: DataStateProps) {
  if (status === 'loading') {
    return (
      <div data-testid="data-state-loading" className={cn('space-y-2 p-3', className)} aria-busy="true">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full rounded-md" />
        ))}
      </div>
    )
  }

  if (status === 'empty') {
    return (
      <Empty data-testid="data-state-empty" className={cn('min-h-[160px] border-0', className)}>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Inbox className="opacity-50" />
          </EmptyMedia>
          <EmptyTitle className="text-sm">{emptyTitle}</EmptyTitle>
          <EmptyDescription className="text-xs">{emptyDescription}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div
      data-testid="data-state-ready"
      className={cn('relative', status === 'stale' && 'stale-data', className)}
    >
      {status === 'stale' && (
        <span className="stale-badge absolute top-2 right-2 z-10 px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/30">
          STALE
        </span>
      )}
      {children}
    </div>
  )
}

/** 由 loading / empty / stale 布尔推导状态 */
export function resolveDataStatus(opts: {
  loading?: boolean
  empty?: boolean
  stale?: boolean
}): DataViewStatus {
  if (opts.loading) return 'loading'
  if (opts.empty) return 'empty'
  if (opts.stale) return 'stale'
  return 'ready'
}
