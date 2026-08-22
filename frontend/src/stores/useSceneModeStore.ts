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
  return 'watch' // 默认盯盘模式（Quotes 主打 K 线视图；避免首屏整体被 MonitorModeLayout 替换导致 K 线不显示）
}

interface SceneModeState {
  /**
   * 当前场景模式。
   * 注意：本 store 的字段名是 `mode`（不是 `sceneMode`）。
   * 正确读取方式：`useSceneModeStore((s) => s.mode)`。
   * 历史曾误写为 `s.sceneMode` 导致永远取到 `undefined`、场景分支永不触发，请勿重蹈覆辙。
   */
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
    // PROD-04 联动：研究场景自动前往左侧「投研」分栏、AI 分析场景渲染全屏，
    // 均由 DashboardLayout 的 useSceneAiBehavior / isAiFullscreen 分支处理，无需在此开抽屉。
  },

  cycleMode: () => {
    const { mode } = get()
    const idx = SCENE_MODES.indexOf(mode)
    const next = SCENE_MODES[(idx + 1) % SCENE_MODES.length]
    get().setMode(next)
  },
}))
