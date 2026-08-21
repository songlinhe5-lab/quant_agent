/**
 * COPILOT-01 重构后：此文件仅保留类型重导出。
 * 状态管理 → `@/stores/useChatStore` (Zustand 单例)。
 * SSE 流式解析 → `./chat-stream-service.ts`。
 * 编排 Hook → `./useChat.ts`。
 * 快捷指令 → `./copilot-quick-commands.ts` (COPILOT-10 单一配置源)。
 */

export type { ChatMessage, ToolStep, ChatAttachment, StrategyBlock, ChartAnnotationPayload } from './types'

// 💡 向后兼容重导出（message-list-area 等仍从此路径引入）
export { STOCK_QUICK_COMMANDS } from './copilot-quick-commands'
export type { StockQuickCommand } from './copilot-quick-commands'
