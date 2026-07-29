import * as React from 'react'

import { cn } from '@/lib/utils'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'

/**
 * 空页面态统一组件（对应 AI_INSTRUCTIONS.md §14.2）。
 * 必须给出「原因文案 + 至少一个引导操作入口」，禁止空白卡片伪装成已加载无内容。
 */
interface EmptyStateProps extends React.ComponentProps<'div'> {
  title?: string
  description?: string
  icon?: React.ReactNode
  /** 引导操作入口，如按钮/链接 */
  action?: React.ReactNode
}

export function EmptyState({
  title = '暂无数据',
  description,
  icon,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <Empty className={cn('py-12', className)} {...props}>
      {icon ? <EmptyMedia variant="icon">{icon}</EmptyMedia> : null}
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        {description ? <EmptyDescription>{description}</EmptyDescription> : null}
      </EmptyHeader>
      {action ? <EmptyContent>{action}</EmptyContent> : null}
    </Empty>
  )
}

export default EmptyState
