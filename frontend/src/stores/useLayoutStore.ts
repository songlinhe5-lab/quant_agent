import { create } from 'zustand'

/**
 * FE-PROD-01: 全局右侧抽屉状态。
 * AI 副驾与 Settings 互斥展开（同一时刻最多一个 open）。
 */
interface LayoutState {
  copilotOpen: boolean
  settingsOpen: boolean
  openCopilot: () => void
  closeCopilot: () => void
  toggleCopilot: () => void
  openSettings: () => void
  closeSettings: () => void
  toggleSettings: () => void
  closeRightDrawers: () => void
}

export const useLayoutStore = create<LayoutState>((set, get) => ({
  copilotOpen: false,
  settingsOpen: false,

  openCopilot: () => set({ copilotOpen: true, settingsOpen: false }),
  closeCopilot: () => set({ copilotOpen: false }),
  toggleCopilot: () => {
    const { copilotOpen } = get()
    if (copilotOpen) {
      set({ copilotOpen: false })
    } else {
      set({ copilotOpen: true, settingsOpen: false })
    }
  },

  openSettings: () => set({ settingsOpen: true, copilotOpen: false }),
  closeSettings: () => set({ settingsOpen: false }),
  toggleSettings: () => {
    const { settingsOpen } = get()
    if (settingsOpen) {
      set({ settingsOpen: false })
    } else {
      set({ settingsOpen: true, copilotOpen: false })
    }
  },

  closeRightDrawers: () => set({ copilotOpen: false, settingsOpen: false }),
}))
