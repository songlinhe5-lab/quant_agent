/**
 * STRAT-04: Auto-Debug 闭环测试
 * 验证结构化错误 + 熔断逻辑
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useStrategyStore } from '../stores'

describe('STRAT-04: Auto-Debug Circuit Breaker', () => {
  beforeEach(() => {
    useStrategyStore.setState({
      fixAttemptCount: 0,
      fixErrorRef: null,
      structuredError: null,
    })
  })

  describe('Circuit Breaker', () => {
    it('should start with 0 attempts', () => {
      const state = useStrategyStore.getState()
      expect(state.fixAttemptCount).toBe(0)
      expect(state.fixErrorRef).toBeNull()
    })

    it('first attempt with new errorRef should succeed', () => {
      const { incrementFixAttempt } = useStrategyStore.getState()
      const result = incrementFixAttempt('error-1')
      
      expect(result).toBe(true)
      const state = useStrategyStore.getState()
      expect(state.fixAttemptCount).toBe(1)
      expect(state.fixErrorRef).toBe('error-1')
    })

    it('second attempt with same errorRef should succeed', () => {
      const { incrementFixAttempt } = useStrategyStore.getState()
      incrementFixAttempt('error-1')
      
      const result = incrementFixAttempt('error-1')
      
      expect(result).toBe(true)
      expect(useStrategyStore.getState().fixAttemptCount).toBe(2)
    })

    it('third attempt with same errorRef should succeed', () => {
      const { incrementFixAttempt } = useStrategyStore.getState()
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      
      const result = incrementFixAttempt('error-1')
      
      expect(result).toBe(true)
      expect(useStrategyStore.getState().fixAttemptCount).toBe(3)
    })

    it('fourth attempt with same errorRef should be blocked (circuit broken)', () => {
      const { incrementFixAttempt } = useStrategyStore.getState()
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      
      const result = incrementFixAttempt('error-1')
      
      expect(result).toBe(false)
      expect(useStrategyStore.getState().fixAttemptCount).toBe(3)  // Not incremented
    })

    it('different errorRef should reset counter', () => {
      const { incrementFixAttempt } = useStrategyStore.getState()
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      // Circuit broken for error-1
      
      // New error should reset
      const result = incrementFixAttempt('error-2')
      
      expect(result).toBe(true)
      const state = useStrategyStore.getState()
      expect(state.fixAttemptCount).toBe(1)
      expect(state.fixErrorRef).toBe('error-2')
    })

    it('resetFixAttempts should clear state', () => {
      const { incrementFixAttempt, resetFixAttempts } = useStrategyStore.getState()
      incrementFixAttempt('error-1')
      incrementFixAttempt('error-1')
      
      resetFixAttempts()
      
      const state = useStrategyStore.getState()
      expect(state.fixAttemptCount).toBe(0)
      expect(state.fixErrorRef).toBeNull()
    })
  })

  describe('Structured Error', () => {
    it('structuredError should be null initially', () => {
      const state = useStrategyStore.getState()
      expect(state.structuredError).toBeNull()
    })

    it('setStructuredError should update state', () => {
      const { setStructuredError } = useStrategyStore.getState()
      const error = {
        exc_type: 'ZeroDivisionError',
        exc_message: 'division by zero',
        lineno: 42,
        traceback: '...',
        debug_tail: [],
      }
      
      setStructuredError(error)
      
      expect(useStrategyStore.getState().structuredError).toEqual(error)
    })

    it('setStructuredError(null) should clear error', () => {
      const { setStructuredError } = useStrategyStore.getState()
      setStructuredError({
        exc_type: 'Error',
        exc_message: 'test',
        lineno: null,
        traceback: '',
        debug_tail: [],
      })
      
      setStructuredError(null)
      
      expect(useStrategyStore.getState().structuredError).toBeNull()
    })
  })
})
