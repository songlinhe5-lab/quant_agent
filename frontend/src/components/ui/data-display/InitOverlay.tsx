import * as React from 'react'

import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * 初始化态遮罩（对应 AI_INSTRUCTIONS.md §14.2）。
 * 首屏加载 / WS 连接中 / 订阅建立中 / 数据回填中必须给出可见反馈，
 * 禁止静默白屏或卡死。
 */
interface InitOverlayProps extends React.ComponentProps<'div'> {
  label?: string
  variant?: 'skeleton' | 'spinner'
  /** 可选进度 0-100，渲染进度条（用于已知进度的长任务，如回测推演） */
  progress?: number
}

export function InitOverlay({
  label = '数据加载中…',
  variant = 'spinner',
  progress,
  className,
  ...props
}: InitOverlayProps) {
  return (
    <div
      data-slot="init-overlay"
      className={cn(
        'flex min-h-[200px] w-full flex-col items-center justify-center gap-4 rounded-lg text-center',
        className,
      )}
      {...props}
    >
      {variant === 'spinner' ? (
        <span
          className="size-6 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground"
          aria-hidden
        />
      ) : (
        <div className="flex w-full max-w-sm flex-col gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
      {label ? (
        <p className="text-sm text-muted-foreground">{label}</p>
      ) : null}
      {typeof progress === 'number' && (
        <div className="w-full max-w-xs">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/30">
            <div
              className="h-full rounded-full bg-primary transition-all duration-300"
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
          <p className="mt-1.5 text-[11px] font-mono text-muted-foreground/70">{Math.round(progress)}%</p>
        </div>
      )}
    </div>
  )
}

export default InitOverlay
