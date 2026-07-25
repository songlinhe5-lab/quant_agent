/**
 * PROD-11：自定义指标脚本的持久化 store。
 * 用户编写的 Pine 风格表达式在此集中管理，并在图表上实时计算叠加。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface CustomIndicator {
  id: string
  name: string
  /** Pine 风格表达式，如 RSI(14) > KDJ.K */
  expr: string
  /** 叠加线/信号点颜色 */
  color: string
  /** 是否渲染到图表 */
  visible: boolean
}

interface CustomIndicatorState {
  indicators: CustomIndicator[]
  add: (ind: Omit<CustomIndicator, 'id'>) => void
  update: (id: string, patch: Partial<CustomIndicator>) => void
  remove: (id: string) => void
  toggle: (id: string) => void
}

const genId = () =>
  globalThis.crypto?.randomUUID?.() ?? `ci-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`

export const useCustomIndicatorStore = create<CustomIndicatorState>()(
  persist(
    (set) => ({
      indicators: [
        // 预置示例，帮助用户理解语法（默认隐藏，避免干扰首屏）
        { id: 'demo-rsikdj', name: 'RSI(14) > KDJ.K', expr: 'RSI(14) > KDJ.K', color: '#a855f7', visible: false },
        { id: 'demo-golden', name: 'MA5 上穿 MA20', expr: 'CROSS(MA(CLOSE,5), MA(CLOSE,20))', color: '#10b981', visible: false },
      ],
      add: (ind) => set((s) => ({ indicators: [...s.indicators, { ...ind, id: genId() }] })),
      update: (id, patch) =>
        set((s) => ({ indicators: s.indicators.map((x) => (x.id === id ? { ...x, ...patch } : x)) })),
      remove: (id) => set((s) => ({ indicators: s.indicators.filter((x) => x.id !== id) })),
      toggle: (id) =>
        set((s) => ({ indicators: s.indicators.map((x) => (x.id === id ? { ...x, visible: !x.visible } : x)) })),
    }),
    { name: 'quant-custom-indicators' },
  ),
)
