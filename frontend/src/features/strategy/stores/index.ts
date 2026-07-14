/**
 * STRAT-01a: Store 组合入口
 * 将 4 个 Slice 组合为统一的 useStrategyStore hook
 * 向后兼容：所有组件的 useStrategyStore() 调用保持不变
 */
import { create } from 'zustand'
import { type EditorSlice, createEditorSlice } from './slices/editor.slice'
import { type AiSlice, createAiSlice } from './slices/ai.slice'
import { type BacktestSlice, createBacktestSlice } from './slices/backtest.slice'
import { type LayoutSlice, createLayoutSlice } from './slices/layout.slice'

export type StrategyStore = EditorSlice & AiSlice & BacktestSlice & LayoutSlice

export const useStrategyStore = create<StrategyStore>()((...a) => ({
  ...createEditorSlice(...a),
  ...createAiSlice(...a),
  ...createBacktestSlice(...a),
  ...createLayoutSlice(...a),
}))

// Re-export slice types for convenience
export type { EditorSlice } from './slices/editor.slice'
export type { AiSlice, Message, DiffSource, DiffState } from './slices/ai.slice'
export type { BacktestSlice, StructuredError } from './slices/backtest.slice'
export type { LayoutSlice } from './slices/layout.slice'
