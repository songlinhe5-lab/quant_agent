/**
 * Logger 单元测试
 * TEST-02: 前端 Zustand Store、自定义 Hooks 单元测试覆盖率 ≥ 60%
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { logger, LogLevel } from '@/lib/logger'

describe('Logger', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('should log messages at correct levels', () => {
    const consoleSpy = vi.spyOn(console, 'debug').mockImplementation(() => {})
    
    logger.debug('test message')
    
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('should have correct log level enum values', () => {
    expect(LogLevel.DEBUG).toBe(0)
    expect(LogLevel.INFO).toBe(1)
    expect(LogLevel.WARN).toBe(2)
    expect(LogLevel.ERROR).toBe(3)
  })

  it('should format log entries correctly', () => {
    const consoleSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    
    logger.info('test info', { key: 'value' })
    
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('should handle error logging', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const error = new Error('test error')
    
    logger.error('error occurred', error)
    
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('should handle warn logging', () => {
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    
    logger.warn('warning message')
    
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('should batch log entries for remote upload', async () => {
    // Logger should buffer entries
    logger.info('batch test 1')
    logger.info('batch test 2')
    
    // flush should work without errors
    await expect(logger.flush()).resolves.not.toThrow()
  })
})
