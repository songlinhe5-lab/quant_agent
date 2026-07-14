/**
 * STRAT-02: AI Diff 状态机测试
 * 验证 Diff 状态转换和四路径收口
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useStrategyStore } from '../stores'

describe('STRAT-02: AI Diff State Machine', () => {
  beforeEach(() => {
    // Reset store to initial state
    useStrategyStore.setState({
      code: 'original code\nprint("hello")',
      isDirty: false,
      diff: { status: 'idle', original: '', incoming: '', source: 'ai-chat' },
    })
  })

  describe('Diff State Transitions', () => {
    it('should start in idle state', () => {
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
    })

    it('idle -> pendingDiff (ai-chat source)', () => {
      const { enterDiff } = useStrategyStore.getState()
      enterDiff('new code from AI', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.original).toBe('original code\nprint("hello")')
      expect(state.diff.incoming).toBe('new code from AI')
      expect(state.diff.source).toBe('ai-chat')
    })

    it('idle -> pendingDiff (auto-fix source)', () => {
      const { enterDiff } = useStrategyStore.getState()
      enterDiff('fixed code', 'auto-fix', { errorRef: 'error-123' })
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.source).toBe('auto-fix')
      expect(state.diff.meta?.errorRef).toBe('error-123')
    })

    it('idle -> pendingDiff (ast-fix source)', () => {
      const { enterDiff } = useStrategyStore.getState()
      enterDiff('ast fixed code', 'ast-fix')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.source).toBe('ast-fix')
    })

    it('idle -> pendingDiff (hermes source)', () => {
      const { enterDiff } = useStrategyStore.getState()
      enterDiff('hermes code', 'hermes')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.source).toBe('hermes')
    })

    it('idle -> pendingDiff (version-restore source)', () => {
      const { enterDiff } = useStrategyStore.getState()
      enterDiff('restored code', 'version-restore', { versionId: 'v1.0' })
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.diff.source).toBe('version-restore')
      expect(state.diff.meta?.versionId).toBe('v1.0')
    })

    it('pendingDiff -> applied (Apply action)', () => {
      const { enterDiff, applyDiff } = useStrategyStore.getState()
      enterDiff('new code', 'ai-chat')
      expect(useStrategyStore.getState().diff.status).toBe('pendingDiff')
      
      applyDiff()
      
      const state = useStrategyStore.getState()
      expect(state.code).toBe('new code')
      expect(state.isDirty).toBe(true)
      expect(state.diff.status).toBe('idle')
    })

    it('pendingDiff -> idle (Reject action)', () => {
      const { enterDiff, rejectDiff } = useStrategyStore.getState()
      enterDiff('new code', 'ai-chat')
      expect(useStrategyStore.getState().diff.status).toBe('pendingDiff')
      
      rejectDiff()
      
      const state = useStrategyStore.getState()
      expect(state.code).toBe('original code\nprint("hello")')
      expect(state.diff.status).toBe('idle')
    })

    it('resetDiff should reset to idle', () => {
      const { enterDiff, resetDiff } = useStrategyStore.getState()
      enterDiff('new code', 'ai-chat')
      expect(useStrategyStore.getState().diff.status).toBe('pendingDiff')
      
      resetDiff()
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
    })
  })

  describe('Empty Editor Exception', () => {
    it('should skip diff for empty editor', () => {
      useStrategyStore.setState({ code: '' })
      const { enterDiff } = useStrategyStore.getState()
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
      expect(state.code).toBe('new code')
      expect(state.isDirty).toBe(true)
    })

    it('should skip diff for editor with only comments', () => {
      useStrategyStore.setState({ code: '# Just a comment\n# Another comment\n' })
      const { enterDiff } = useStrategyStore.getState()
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
      expect(state.code).toBe('new code')
    })

    it('should skip diff for editor with only whitespace', () => {
      useStrategyStore.setState({ code: '   \n\n   \n' })
      const { enterDiff } = useStrategyStore.getState()
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('idle')
      expect(state.code).toBe('new code')
    })

    it('should NOT skip diff for editor with actual code', () => {
      useStrategyStore.setState({ code: 'print("real code")' })
      const { enterDiff } = useStrategyStore.getState()
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.status).toBe('pendingDiff')
      expect(state.code).toBe('print("real code")')
    })
  })

  describe('State Machine Invariants', () => {
    it('applyDiff should only work in pendingDiff state', () => {
      const { applyDiff } = useStrategyStore.getState()
      
      // Try to apply in idle state
      applyDiff()
      
      const state = useStrategyStore.getState()
      expect(state.code).toBe('original code\nprint("hello")')
      expect(state.diff.status).toBe('idle')
    })

    it('should preserve original code when entering diff', () => {
      const { enterDiff } = useStrategyStore.getState()
      const originalCode = useStrategyStore.getState().code
      
      enterDiff('new code', 'ai-chat')
      
      const state = useStrategyStore.getState()
      expect(state.diff.original).toBe(originalCode)
    })

    it('should store metadata when provided', () => {
      const { enterDiff } = useStrategyStore.getState()
      const meta = { versionId: 'v123', errorRef: 'err456' }
      
      enterDiff('new code', 'version-restore', meta)
      
      const state = useStrategyStore.getState()
      expect(state.diff.meta).toEqual(meta)
    })
  })

  describe('Integration with Editor State', () => {
    it('applyDiff should mark editor as dirty', () => {
      const { enterDiff, applyDiff } = useStrategyStore.getState()
      enterDiff('new code', 'ai-chat')
      
      applyDiff()
      
      const state = useStrategyStore.getState()
      expect(state.isDirty).toBe(true)
    })

    it('rejectDiff should NOT mark editor as dirty', () => {
      const { enterDiff, rejectDiff } = useStrategyStore.getState()
      enterDiff('new code', 'ai-chat')
      
      rejectDiff()
      
      const state = useStrategyStore.getState()
      expect(state.isDirty).toBe(false)
    })
  })
})
