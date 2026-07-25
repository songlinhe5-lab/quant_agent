import { create } from 'zustand'

export type CopilotContextKind = 'screener' | 'kline' | 'risk'

export interface CopilotPageContext {
  kind: CopilotContextKind
  title: string
  summary: string
  /** 当前页面聚焦的标的（仅 kline 页有），供 AI 标注按标的匹配 */
  symbol?: string
}

interface CopilotContextState {
  context: CopilotPageContext | null
  setContext: (ctx: CopilotPageContext | null) => void
  clearContext: () => void
}

/**
 * PROD-01: AI 副驾页面上下文。
 * 各业务页面（选股器 / K线 / 风控）在自身状态变化时写入当前上下文，
 * 全局副驾抽屉读取并在会话首条消息自动注入，实现"场景感知助手"。
 */
export const useCopilotContextStore = create<CopilotContextState>((set) => ({
  context: null,
  setContext: (ctx) => set({ context: ctx }),
  clearContext: () => set({ context: null }),
}))
