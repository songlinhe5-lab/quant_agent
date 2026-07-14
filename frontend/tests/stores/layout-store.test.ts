/**
 * FE-PROD-01: 全局右侧抽屉互斥状态
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useLayoutStore } from '@/stores/useLayoutStore'

describe('useLayoutStore', () => {
  beforeEach(() => {
    act(() => {
      useLayoutStore.getState().closeRightDrawers()
    })
  })

  it('openCopilot closes settings (mutual exclusion)', () => {
    const { result } = renderHook(() => useLayoutStore())

    act(() => {
      result.current.openSettings()
    })
    expect(result.current.settingsOpen).toBe(true)
    expect(result.current.copilotOpen).toBe(false)

    act(() => {
      result.current.openCopilot()
    })
    expect(result.current.copilotOpen).toBe(true)
    expect(result.current.settingsOpen).toBe(false)
  })

  it('openSettings closes copilot (mutual exclusion)', () => {
    const { result } = renderHook(() => useLayoutStore())

    act(() => {
      result.current.openCopilot()
    })
    act(() => {
      result.current.openSettings()
    })
    expect(result.current.settingsOpen).toBe(true)
    expect(result.current.copilotOpen).toBe(false)
  })

  it('toggleCopilot opens then closes', () => {
    const { result } = renderHook(() => useLayoutStore())

    act(() => {
      result.current.toggleCopilot()
    })
    expect(result.current.copilotOpen).toBe(true)

    act(() => {
      result.current.toggleCopilot()
    })
    expect(result.current.copilotOpen).toBe(false)
  })

  it('toggleSettings while copilot open switches exclusively', () => {
    const { result } = renderHook(() => useLayoutStore())

    act(() => {
      result.current.openCopilot()
    })
    act(() => {
      result.current.toggleSettings()
    })
    expect(result.current.settingsOpen).toBe(true)
    expect(result.current.copilotOpen).toBe(false)
  })

  it('closeRightDrawers clears both', () => {
    const { result } = renderHook(() => useLayoutStore())

    act(() => {
      result.current.openCopilot()
    })
    act(() => {
      result.current.closeRightDrawers()
    })
    expect(result.current.copilotOpen).toBe(false)
    expect(result.current.settingsOpen).toBe(false)
  })
})
