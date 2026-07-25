import { create } from 'zustand'
import type { ChartAnnotationPayload } from '../features/copilot/types'

interface ChartAnnotationState {
  /** 当前生效标注对应的标的（原始字符串，比较时由消费方归一化） */
  symbol: string | null
  payload: ChartAnnotationPayload | null
  /** 写入一组标注（通常来自 AI 副驾的结构化输出） */
  setAnnotation: (symbol: string, payload: ChartAnnotationPayload) => void
  /** 清空当前标注 */
  clear: () => void
}

/**
 * PROD-02：承载 AI 副驾解析出的图表标注，供 K 线图组件订阅渲染。
 * 与 useCopilotContextStore 解耦，仅通过 symbol 匹配当前图表标的。
 */
export const useChartAnnotationStore = create<ChartAnnotationState>((set) => ({
  symbol: null,
  payload: null,
  setAnnotation: (symbol, payload) => set({ symbol, payload }),
  clear: () => set({ symbol: null, payload: null }),
}))
