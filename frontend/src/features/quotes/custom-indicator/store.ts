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
  /** 用户自定义参数：@name -> 数值，运行时代入表达式（如 { period: 5 }） */
  params?: Record<string, number>
  /** 叠加线/信号点颜色 */
  color: string
  /** 是否渲染到图表 */
  visible: boolean
  /**
   * 叠加方式：'overlay' 主图价格坐标 | 'separate' 独立副图坐标 | undefined 自动（默认按 suggestPane）
   * 振荡类指标（RSI/KDJ/MACD/BB）默认 separate，避免主图价格尺度被扭曲。
   */
  pane?: 'overlay' | 'separate'
}

/** 信号触发记录：布尔指标在末根 K 线上穿（0->1 跳变）时写入，供提醒/回测消费 */
export interface CISignal {
  indId: string
  indName: string
  expr: string
  /** 触发 K 线日期（YYYY-MM-DD） */
  time: string
  /** 触发时间戳（毫秒） */
  ts: number
}

interface CustomIndicatorState {
  indicators: CustomIndicator[]
  signalLog: CISignal[]
  add: (ind: Omit<CustomIndicator, 'id'>) => void
  update: (id: string, patch: Partial<CustomIndicator>) => void
  remove: (id: string) => void
  toggle: (id: string) => void
  pushSignal: (s: CISignal) => void
  clearSignals: () => void
}

const genId = () =>
  globalThis.crypto?.randomUUID?.() ?? `ci-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`

const MAX_SIGNALS = 50

export const useCustomIndicatorStore = create<CustomIndicatorState>()(
  persist(
    (set) => ({
      indicators: [
        // 预置示例，帮助用户理解语法（默认隐藏，避免干扰首屏）
        { id: 'demo-rsi', name: 'RSI(14)', expr: 'RSI(14)', color: '#f59e0b', visible: false, pane: 'separate' },
        { id: 'demo-rsikdj', name: 'RSI(14) > KDJ.K', expr: 'RSI(14) > KDJ.K', color: '#a855f7', visible: false },
        { id: 'demo-golden', name: 'MA5 上穿 MA20', expr: 'CROSS(MA(CLOSE,5), MA(CLOSE,20))', color: '#10b981', visible: false },
      ],
      signalLog: [],
      add: (ind) => set((s) => ({ indicators: [...s.indicators, { ...ind, id: genId() }] })),
      update: (id, patch) =>
        set((s) => ({ indicators: s.indicators.map((x) => (x.id === id ? { ...x, ...patch } : x)) })),
      remove: (id) => set((s) => ({ indicators: s.indicators.filter((x) => x.id !== id) })),
      toggle: (id) =>
        set((s) => ({ indicators: s.indicators.map((x) => (x.id === id ? { ...x, visible: !x.visible } : x)) })),
      pushSignal: (sig) =>
        set((s) => ({ signalLog: [sig, ...s.signalLog].slice(0, MAX_SIGNALS) })),
      clearSignals: () => set({ signalLog: [] }),
    }),
    { name: 'quant-custom-indicators' },
  ),
)
