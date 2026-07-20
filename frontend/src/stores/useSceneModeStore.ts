import { create } from 'zustand'
import { SCENE_MODES, type SceneMode } from '@/features/scene/scene-mode-types'

const STORAGE_KEY = 'quant_scene_mode'

function loadInitialMode(): SceneMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && SCENE_MODES.includes(stored as SceneMode)) {
      return stored as SceneMode
    }
  } catch {
    /* SSR or localStorage unavailable */
  }
  return 'monitor' // 默认监控模式（最通用的日常模式）
}

interface SceneModeState {
  mode: SceneMode
  setMode: (m: SceneMode) => void
  /** Cmd+Shift+M 循环切换到下一个模式 */
  cycleMode: () => void
}

export const useSceneModeStore = create<SceneModeState>((set, get) => ({
  mode: loadInitialMode(),

  setMode: (mode) => {
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* ignore */
    }
    set({ mode })
  },

  cycleMode: () => {
    const { mode } = get()
    const idx = SCENE_MODES.indexOf(mode)
    const next = SCENE_MODES[(idx + 1) % SCENE_MODES.length]
    get().setMode(next)
  },
}))
