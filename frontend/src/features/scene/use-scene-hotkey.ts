import { useEffect } from 'react'
import { useSceneModeStore } from '@/stores/useSceneModeStore'

/**
 * PROD-04: Cmd+Shift+M 循环切换场景模式
 */
export function useSceneHotkey() {
  const cycleMode = useSceneModeStore((s) => s.cycleMode)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return
      if (e.key.toLowerCase() !== 'm') return
      e.preventDefault()
      cycleMode()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [cycleMode])
}
