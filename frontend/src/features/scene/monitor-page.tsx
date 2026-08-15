'use client'

import { MonitorModeLayout } from '@/features/scene/monitor-mode-layout'
import { ModuleErrorBoundary } from '@/components/error-boundary'

/**
 * 监控总览独立页面（/monitor）
 * 2026-08-14：监控总览从 Quotes 模块劫持改为独立路由入口，
 * Quotes 页永远渲染标准行情 K 线布局，不再被监控场景顶替。
 */
export function MonitorPage() {
  return (
    <ModuleErrorBoundary name="Monitor">
      <MonitorModeLayout />
    </ModuleErrorBoundary>
  )
}
