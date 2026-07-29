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
}

export function InitOverlay({
  label = '数据加载中…',
  variant = 'spinner',
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
    </div>
  )
}

export default InitOverlay
