/**
 * COPILOT-01 重构后：此文件仅保留共享常量与类型重导出。
 * 状态管理已迁移至 `@/stores/useChatStore` (Zustand 单例)。
 * SSE 流式解析已迁移至 `./chat-stream-service.ts`。
 * 编排 Hook 已迁移至 `./useChat.ts`。
 */

import type { ChatMessage, ToolStep, ChatAttachment, StrategyBlock, ChartAnnotationPayload } from './types'

export type { ChatMessage, ToolStep, ChatAttachment, StrategyBlock, ChartAnnotationPayload } from './types'

/** 个股深度研判快捷指令定义 */
export interface StockQuickCommand {
  emoji: string
  label: string
  template: string
}

export const STOCK_QUICK_COMMANDS: StockQuickCommand[] = [
  { emoji: '📊', label: '个股深度研判', template: '请对 {输入标的} 进行深度研判，综合基本面、技术面和估值，给出投资建议。' },
  { emoji: '🔄', label: '对标分析', template: '请将 {输入标的} 与行业内 top 3 竞品进行对标分析。' },
  { emoji: '⚠️', label: '财务异常检测', template: '请检测 {输入标的} 是否存在财务异常信号。' },
  { emoji: '🎯', label: '目标价评估', template: '请评估 {输入标的} 12个月目标价空间，给出悲观/中性/乐观三档估值。' },
]
