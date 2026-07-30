import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * 数据来源提示徽章（对应 AI_INSTRUCTIONS.md §14.3）。
 * 任何外部行情/财务/新闻面板必须标注数据源名称 + 更新时间；
 * 异常/降级时 stale=true，降级为 amber STALE 徽章。
 */
interface DataSourceBadgeProps extends React.ComponentProps<'span'> {
  source: string
  /** 已格式化的更新时间字符串 */
  updatedAt?: string | null
  stale?: boolean
}

export function DataSourceBadge({
  source,
  updatedAt,
  stale = false,
  className,
  ...props
}: DataSourceBadgeProps) {
  return (
    <span
      data-slot="data-source-badge"
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium',
        stale
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-400'
          : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400',
        className,
      )}
      {...props}
    >
      <span
        className={cn(
          'size-1.5 rounded-full',
          stale ? 'bg-amber-400' : 'bg-emerald-400',
        )}
      />
      {stale ? 'STALE' : '数据源'}: {source}
      {updatedAt ? (
        <span className="text-muted-foreground">· 更新于 {updatedAt}</span>
      ) : null}
    </span>
  )
}

export default DataSourceBadge
