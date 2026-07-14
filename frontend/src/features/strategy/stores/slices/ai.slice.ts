/**
 * STRAT-01a: AI Slice — 对话历史 / 流式状态 / Diff 状态机 (STRAT-02 预留)
 */
import { StateCreator } from 'zustand'
import type { StrategyStore } from '../index'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  status?: 'typing' | 'reasoning' | 'done' | 'error'
}

export type DiffSource = 'ai-chat' | 'auto-fix' | 'ast-fix' | 'hermes' | 'version-restore'

export interface DiffState {
  status: 'idle' | 'streaming' | 'pendingDiff'
  original: string
  incoming: string
  source: DiffSource
  meta?: { versionId?: string; errorRef?: string }
}

export interface AiSlice {
  messages: Message[]
  isGenerating: boolean
  addMessage: (msg: Message) => void
  updateMessage: (id: string, updater: Partial<Message>) => void
  setGenerating: (generating: boolean) => void
  clearMessages: () => void
  // Diff state machine (STRAT-02)
  diff: DiffState
  enterDiff: (incoming: string, source: DiffSource, meta?: DiffState['meta']) => void
  applyDiff: () => void
  rejectDiff: () => void
  resetDiff: () => void
  // STRAT-04: Circuit breaker
  fixAttemptCount: number
  fixErrorRef: string | null
  incrementFixAttempt: (errorRef: string) => boolean  // returns false if circuit broken
  resetFixAttempts: () => void
}

const WELCOME_MSG: Message = {
  id: '1',
  role: 'assistant',
  content: '你好！我是你的量化策略 Copilot。你可以告诉我你的交易想法，例如："写一个基于 RSI 的双均线策略，单笔仓位 5%"。',
  status: 'done',
}

const initialDiff: DiffState = {
  status: 'idle',
  original: '',
  incoming: '',
  source: 'ai-chat',
}

export const createAiSlice: StateCreator<StrategyStore, [], [], AiSlice> = (set, get) => ({
  messages: [WELCOME_MSG],
  isGenerating: false,
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  updateMessage: (id, updater) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...updater } : m)),
    })),
  setGenerating: (generating) => set({ isGenerating: generating }),
  clearMessages: () => set({ messages: [{ ...WELCOME_MSG }] }),

  // Diff state machine
  diff: { ...initialDiff },
  enterDiff: (incoming, source, meta) => {
    const state = get()
    const currentCode = state.code
    // Empty editor exception: skip Diff, apply directly
    const isEmpty = !currentCode.trim() || /^[\s\n]*($|#[^\n]*\n)*$/.test(currentCode)
    if (isEmpty) {
      set({ code: incoming, isDirty: true, diff: { ...initialDiff } })
      return
    }
    set({
      diff: { status: 'pendingDiff', original: currentCode, incoming, source, meta },
    })
  },
  applyDiff: () => {
    const { diff } = get()
    if (diff.status !== 'pendingDiff') return
    set({ code: diff.incoming, isDirty: true, diff: { ...initialDiff } })
  },
  rejectDiff: () => {
    set({ diff: { ...initialDiff } })
  },
  resetDiff: () => {
    set({ diff: { ...initialDiff } })
  },

  // STRAT-04: Circuit breaker
  fixAttemptCount: 0,
  fixErrorRef: null,
  incrementFixAttempt: (errorRef) => {
    const state = get()
    // Different error -> reset counter
    if (state.fixErrorRef !== errorRef) {
      set({ fixAttemptCount: 1, fixErrorRef: errorRef })
      return true
    }
    // Same error -> increment
    if (state.fixAttemptCount >= 3) {
      return false  // Circuit broken
    }
    set({ fixAttemptCount: state.fixAttemptCount + 1 })
    return true
  },
  resetFixAttempts: () => {
    set({ fixAttemptCount: 0, fixErrorRef: null })
  },
})
