import { create } from 'zustand'
import { apiClient } from '@/lib/api-client'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  status?: 'typing' | 'reasoning' | 'done' | 'error'
}

interface StrategyState {
  // Strategy Explorer Slice
  activeStrategy: string
  setActiveStrategy: (name: string) => void
  strategies: any[]
  setStrategies: (list: any[]) => void
  favorites: string[]
  setFavorites: (favs: string[]) => void
  fetchStrategies: () => Promise<void>

  // Layout Slice
  leftSidebarOpen: boolean
  rightSidebarOpen: boolean
  activeWorkspaceTab: 'code' | 'report'
  setWorkspaceTab: (tab: 'code' | 'report') => void

  // Editor Slice
  code: string
  isDirty: boolean
  setCode: (code: string) => void
  setIsDirty: (isDirty: boolean) => void
  lastSavedCode: string
  setLastSavedCode: (code: string) => void

  // AI Chat Slice
  messages: Message[]
  isGenerating: boolean
  addMessage: (msg: Message) => void
  updateMessage: (id: string, updater: Partial<Message>) => void
  setGenerating: (generating: boolean) => void
  clearMessages: () => void

  // Backtest & Form Config Slice
  formSchema: any[]
  setFormSchema: (schema: any[]) => void
  testTicker: string
  setTestTicker: (ticker: string) => void
  initialCapital: string
  setInitialCapital: (cap: string) => void
  backtestPeriod: string
  setBacktestPeriod: (period: string) => void
  dataSource: string
  setDataSource: (source: string) => void
  isDebugMode: boolean
  setIsDebugMode: (debug: boolean) => void
  savedPresets: Record<string, Record<string, any>>
  setSavedPresets: (presets: Record<string, Record<string, any>>) => void
  lastUsedClassName: string
  setLastUsedClassName: (name: string) => void
  lastUsedParams: Record<string, any>
  setLastUsedParams: (params: Record<string, any>) => void

  // Backtest Engine State
  isSimulating: boolean
  setSimulating: (sim: boolean) => void
  backtestResult: any
  setBacktestResult: (res: any) => void
  runtimeError: string | null
  setRuntimeError: (err: string | null) => void
  isOptimizing: boolean
  setOptimizing: (opt: boolean) => void
  optimizationResults: any[] | null
  setOptimizationResults: (res: any[] | null) => void
  optimizedClassName: string
  setOptimizedClassName: (name: string) => void
}

export const useStrategyStore = create<StrategyState>((set) => ({
  // Strategy Explorer
  activeStrategy: '',
  setActiveStrategy: (activeStrategy) => set({ activeStrategy }),
  strategies: [],
  setStrategies: (strategies) => set({ strategies }),
  favorites: [],
  setFavorites: (favorites) => set({ favorites }),
  fetchStrategies: async () => {
    try {
      const res = await apiClient.get('/strategy/list')
      if (res.data?.status === 'success') {
        set({ strategies: res.data.data })
      }
    } catch (e) {
      console.error('Failed to fetch strategies:', e)
    }
  },

  // Layout
  leftSidebarOpen: true,
  rightSidebarOpen: true,
  activeWorkspaceTab: 'code',
  setWorkspaceTab: (tab) => set({ activeWorkspaceTab: tab }),

  // Editor
  code: '# Draft Strategy...\n',
  isDirty: false,
  setCode: (code) => set({ code, isDirty: true }),
  setIsDirty: (isDirty) => set({ isDirty }),
  lastSavedCode: '# Draft Strategy...\n',
  setLastSavedCode: (lastSavedCode) => set({ lastSavedCode, isDirty: false }),

  // AI Chat
  messages: [
    { 
      id: '1', 
      role: 'assistant', 
      content: '你好！我是你的量化策略 Copilot。你可以告诉我你的交易想法，例如：“写一个基于 RSI 的双均线策略，单笔仓位 5%”。', 
      status: 'done' 
    }
  ],
  isGenerating: false,
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  updateMessage: (id, updater) => set((state) => ({
    messages: state.messages.map((m) => (m.id === id ? { ...m, ...updater } : m))
  })),
  setGenerating: (generating) => set({ isGenerating: generating }),
  clearMessages: () => set({ 
    messages: [{ id: '1', role: 'assistant', content: '你好！我是你的量化策略 Copilot。你可以告诉我你的交易想法。', status: 'done' }] 
  }),

  // Backtest & Form Config
  formSchema: [],
  setFormSchema: (formSchema) => set({ formSchema }),
  testTicker: 'US.AAPL',
  setTestTicker: (testTicker) => set({ testTicker }),
  initialCapital: '100000',
  setInitialCapital: (initialCapital) => set({ initialCapital }),
  backtestPeriod: '1y',
  setBacktestPeriod: (backtestPeriod) => set({ backtestPeriod }),
  dataSource: 'auto',
  setDataSource: (dataSource) => set({ dataSource }),
  isDebugMode: false,
  setIsDebugMode: (isDebugMode) => set({ isDebugMode }),
  savedPresets: {},
  setSavedPresets: (savedPresets) => set({ savedPresets }),
  lastUsedClassName: '',
  setLastUsedClassName: (lastUsedClassName) => set({ lastUsedClassName }),
  lastUsedParams: {},
  setLastUsedParams: (lastUsedParams) => set({ lastUsedParams }),
  
  // Backtest Engine State
  isSimulating: false,
  setSimulating: (isSimulating) => set({ isSimulating }),
  backtestResult: null,
  setBacktestResult: (backtestResult) => set({ backtestResult }),
  runtimeError: null,
  setRuntimeError: (runtimeError) => set({ runtimeError }),
  isOptimizing: false,
  setOptimizing: (isOptimizing) => set({ isOptimizing }),
  optimizationResults: null,
  setOptimizationResults: (optimizationResults) => set({ optimizationResults }),
  optimizedClassName: '',
  setOptimizedClassName: (optimizedClassName) => set({ optimizedClassName })
}))
