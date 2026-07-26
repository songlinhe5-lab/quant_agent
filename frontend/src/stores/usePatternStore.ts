import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChartAnnotationPayload } from '@/features/copilot/types'
import { STORAGE_KEYS } from '@/lib/constants'

interface PatternState {
  /** 是否开启形态识别叠加（与 AI 副驾标注相互独立） */
  enabled: boolean
  /** 当前生效形态标注对应的标的 */
  symbol: string | null
  payload: ChartAnnotationPayload | null
  setEnabled: (v: boolean) => void
  setPattern: (symbol: string, payload: ChartAnnotationPayload | null) => void
}

/**
 * AI-01 能力②：形态识别标注存储。
 * 与 useChartAnnotationStore（AI 副驾）解耦，避免相互覆盖；K 线图订阅后独立渲染。
 */
export const usePatternStore = create<PatternState>()(
  persist(
    (set) => ({
      enabled: true,
      symbol: null,
      payload: null,
      setEnabled: (v) => set({ enabled: v }),
      setPattern: (symbol, payload) => set({ symbol: payload ? symbol : null, payload }),
    }),
    { name: STORAGE_KEYS.pattern },
  ),
)
