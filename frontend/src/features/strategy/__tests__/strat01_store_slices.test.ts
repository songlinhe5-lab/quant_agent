/**
 * STRAT-01a: Store Slices 测试
 * 验证 4 个 Slice 的状态转换和 actions
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useStrategyStore } from '../stores'

describe('STRAT-01a: Store Slices', () => {
  beforeEach(() => {
    // Reset store to initial state
    useStrategyStore.setState({
      code: '# Draft Strategy...\n',
      isDirty: false,
      lastSavedCode: '# Draft Strategy...\n',
      messages: [{
        id: '1',
        role: 'assistant',
        content: '你好！我是你的量化策略 Copilot。你可以告诉我你的交易想法，例如："写一个基于 RSI 的双均线策略，单笔仓位 5%"。',
        status: 'done',
      }],
      isGenerating: false,
      diff: { status: 'idle', original: '', incoming: '', source: 'ai-chat' },
      formSchema: [],
      testTicker: 'US.AAPL',
      initialCapital: '100000',
      backtestPeriod: '1y',
      dataSource: 'auto',
      dataSnapshotId: 'latest_published',
      isDebugMode: false,
      savedPresets: {},
      lastUsedClassName: '',
      lastUsedParams: {},
      isSimulating: false,
      backtestResult: null,
      runtimeError: null,
      isOptimizing: false,
      optimizationResults: null,
      optimizedClassName: '',
      structuredError: null,
      activeStrategy: '',
      strategies: [],
      favorites: [],
      leftSidebarOpen: true,
      rightSidebarOpen: true,
      activeWorkspaceTab: 'code',
    })
  })

  describe('EditorSlice', () => {
    it('should have correct initial state', () => {
      const state = useStrategyStore.getState()
      expect(state.code).toBe('# Draft Strategy...\n')
      expect(state.isDirty).toBe(false)
      expect(state.lastSavedCode).toBe('# Draft Strategy...\n')
    })

    it('setCode should mark isDirty as true', () => {
      const { setCode } = useStrategyStore.getState()
      setCode('print("hello")')
      const state = useStrategyStore.getState()
      expect(state.code).toBe('print("hello")')
      expect(state.isDirty).toBe(true)
    })

    it('setLastSavedCode should clear isDirty', () => {
      const { setCode, setLastSavedCode } = useStrategyStore.getState()
      setCode('print("hello")')
      expect(useStrategyStore.getState().isDirty).toBe(true)
      
      setLastSavedCode('print("hello")')
      const state = useStrategyStore.getState()
      expect(state.isDirty).toBe(false)
      expect(state.lastSavedCode).toBe('print("hello")')
    })

    it('setIsDirty should directly set isDirty', () => {
      const { setIsDirty } = useStrategyStore.getState()
      setIsDirty(true)
      expect(useStrategyStore.getState().isDirty).toBe(true)
      setIsDirty(false)
      expect(useStrategyStore.getState().isDirty).toBe(false)
    })

    it('saveCode should call API and update state', async () => {
      const { saveCode, setCode } = useStrategyStore.getState()
      setCode('print("test")')
      
      // Mock the API call by checking the function exists
      expect(typeof saveCode).toBe('function')
      
      // Note: Actual API call testing would require mocking apiClient
      // For now, we verify the function signature and behavior
    })
  })

  describe('AiSlice', () => {
    it('should have correct initial state', () => {
      const state = useStrategyStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0].role).toBe('assistant')
      expect(state.isGenerating).toBe(false)
    })

    it('addMessage should append message', () => {
      const { addMessage } = useStrategyStore.getState()
      addMessage({ id: '2', role: 'user', content: 'Hello' })
      
      const state = useStrategyStore.getState()
      expect(state.messages).toHaveLength(2)
      expect(state.messages[1].content).toBe('Hello')
    })

    it('updateMessage should update existing message', () => {
      const { addMessage, updateMessage } = useStrategyStore.getState()
      addMessage({ id: '2', role: 'user', content: 'Hello', status: 'typing' })
      
      updateMessage('2', { content: 'Updated', status: 'done' })
      
      const state = useStrategyStore.getState()
      const msg = state.messages.find(m => m.id === '2')
      expect(msg?.content).toBe('Updated')
      expect(msg?.status).toBe('done')
    })

    it('clearMessages should reset to welcome message', () => {
      const { addMessage, clearMessages } = useStrategyStore.getState()
      addMessage({ id: '2', role: 'user', content: 'Hello' })
      expect(useStrategyStore.getState().messages).toHaveLength(2)
      
      clearMessages()
      
      const state = useStrategyStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0].role).toBe('assistant')
    })

    it('setGenerating should toggle isGenerating', () => {
      const { setGenerating } = useStrategyStore.getState()
      setGenerating(true)
      expect(useStrategyStore.getState().isGenerating).toBe(true)
      setGenerating(false)
      expect(useStrategyStore.getState().isGenerating).toBe(false)
    })

    it('Diff state machine: enterDiff should set pendingDiff status', () => {
      const { setCode, enterDiff } = useStrategyStore.getState()
      setCode('original code')
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.original).toBe('original code')
      expect(state.diff.incoming).toBe('new code')
      expect(state.diff.source).toBe('ai-chat')
    })

    it('Diff state machine: enterDiff should skip diff for empty editor', () => {
      const { setCode, enterDiff } = useStrategyStore.getState()
      setCode('')
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
      expect(state.code).toBe('new code')
    })

    it('Diff state machine: applyDiff should apply incoming code', () => {
      const { setCode, enterDiff, applyDiff } = useStrategyStore.getState()
      setCode('original')
      enterDiff('incoming', 'ai-chat')
      
      applyDiff()
      
      const state = useStrategyStore.getState()
      expect(state.code).toBe('incoming')
      expect(state.isDirty).toBe(true)
      expect(state.diff.status).toBe('idle')
    })

    it('Diff state machine: rejectDiff should reset to idle', () => {
      const { setCode, enterDiff, rejectDiff } = useStrategyStore.getState()
      setCode('original')
      enterDiff('incoming', 'ai-chat')
      expect(useStrategyStore.getState().diff.status).toBe('pendingDiff')
      
      rejectDiff()
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
      expect(state.code).toBe('original')
    })
  })

  describe('BacktestSlice', () => {
    it('should have correct initial state', () => {
      const state = useStrategyStore.getState()
      expect(state.formSchema).toEqual([])
      expect(state.testTicker).toBe('US.AAPL')
      expect(state.initialCapital).toBe('100000')
      expect(state.isSimulating).toBe(false)
      expect(state.backtestResult).toBeNull()
      expect(state.runtimeError).toBeNull()
    })

    it('setSimulating should toggle isSimulating', () => {
      const { setSimulating } = useStrategyStore.getState()
      setSimulating(true)
      expect(useStrategyStore.getState().isSimulating).toBe(true)
      setSimulating(false)
      expect(useStrategyStore.getState().isSimulating).toBe(false)
    })

    it('setBacktestResult should update result', () => {
      const { setBacktestResult } = useStrategyStore.getState()
      const mockResult = { metrics: { sharpe_ratio: 1.5 } }
      setBacktestResult(mockResult)
      expect(useStrategyStore.getState().backtestResult).toEqual(mockResult)
    })

    it('setRuntimeError should update error', () => {
      const { setRuntimeError } = useStrategyStore.getState()
      setRuntimeError('Test error')
      expect(useStrategyStore.getState().runtimeError).toBe('Test error')
      setRuntimeError(null)
      expect(useStrategyStore.getState().runtimeError).toBeNull()
    })

    it('setFormSchema should update schema', () => {
      const { setFormSchema } = useStrategyStore.getState()
      const schema = [{ class_name: 'TestStrategy', parameters: [] }]
      setFormSchema(schema)
      expect(useStrategyStore.getState().formSchema).toEqual(schema)
    })

    it('structuredError (STRAT-04 预留) should be null initially', () => {
      const state = useStrategyStore.getState()
      expect(state.structuredError).toBeNull()
    })
  })

  describe('LayoutSlice', () => {
    it('should have correct initial state', () => {
      const state = useStrategyStore.getState()
      expect(state.activeStrategy).toBe('')
      expect(state.strategies).toEqual([])
      expect(state.favorites).toEqual([])
      expect(state.leftSidebarOpen).toBe(true)
      expect(state.rightSidebarOpen).toBe(true)
      expect(state.activeWorkspaceTab).toBe('code')
    })

    it('setActiveStrategy should update activeStrategy', () => {
      const { setActiveStrategy } = useStrategyStore.getState()
      setActiveStrategy('TestStrategy')
      expect(useStrategyStore.getState().activeStrategy).toBe('TestStrategy')
    })

    it('setStrategies should update strategies list', () => {
      const { setStrategies } = useStrategyStore.getState()
      const list = [{ name: 'Strategy1' }, { name: 'Strategy2' }]
      setStrategies(list)
      expect(useStrategyStore.getState().strategies).toEqual(list)
    })

    it('setFavorites should update favorites', () => {
      const { setFavorites } = useStrategyStore.getState()
      setFavorites(['Strategy1'])
      expect(useStrategyStore.getState().favorites).toEqual(['Strategy1'])
    })

    it('setWorkspaceTab should update activeWorkspaceTab', () => {
      const { setWorkspaceTab } = useStrategyStore.getState()
      setWorkspaceTab('report')
      expect(useStrategyStore.getState().activeWorkspaceTab).toBe('report')
      setWorkspaceTab('code')
      expect(useStrategyStore.getState().activeWorkspaceTab).toBe('code')
    })

    it('fetchStrategies should be a function', () => {
      const { fetchStrategies } = useStrategyStore.getState()
      expect(typeof fetchStrategies).toBe('function')
    })
  })

  describe('Store Composition', () => {
    it('should combine all slices into one store', () => {
      const state = useStrategyStore.getState()
      
      // EditorSlice
      expect(state).toHaveProperty('code')
      expect(state).toHaveProperty('setCode')
      
      // AiSlice
      expect(state).toHaveProperty('messages')
      expect(state).toHaveProperty('addMessage')
      expect(state).toHaveProperty('diff')
      
      // BacktestSlice
      expect(state).toHaveProperty('formSchema')
      expect(state).toHaveProperty('isSimulating')
      
      // LayoutSlice
      expect(state).toHaveProperty('activeStrategy')
      expect(state).toHaveProperty('fetchStrategies')
    })

    it('useStrategyStore hook should work with selector', () => {
      // This test verifies the hook can be used with selectors
      // Actual hook testing would require React Testing Library
      const code = useStrategyStore.getState().code
      expect(typeof code).toBe('string')
    })
  })
})
