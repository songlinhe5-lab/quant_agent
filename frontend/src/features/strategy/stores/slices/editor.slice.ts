/**
 * STRAT-01a: Editor Slice — 编辑器源码 / 脏标记 / 格式化状态
 */
import { StateCreator } from 'zustand'
import { apiClient } from '@/lib/api-client'
import type { StrategyStore } from '../index'

export interface EditorSlice {
  code: string
  isDirty: boolean
  lastSavedCode: string
  setCode: (code: string) => void
  setIsDirty: (isDirty: boolean) => void
  setLastSavedCode: (code: string) => void
  saveCode: (className?: string) => Promise<{ success: boolean; formattedCode?: string; message?: string }>
}

export const initialEditorState = {
  code: '# Draft Strategy...\n',
  isDirty: false,
  lastSavedCode: '# Draft Strategy...\n',
}

export const createEditorSlice: StateCreator<StrategyStore, [], [], EditorSlice> = (set, get) => ({
  ...initialEditorState,
  setCode: (code) => set({ code, isDirty: true }),
  setIsDirty: (isDirty) => set({ isDirty }),
  setLastSavedCode: (lastSavedCode) => set({ lastSavedCode, isDirty: false }),
  saveCode: async (className) => {
    const state = get()
    const codeToSave = state.code
    const name = className || 'DraftStrategy'
    try {
      const res = await apiClient.post('/strategy/save', { source_code: codeToSave, class_name: name })
      if (res.data?.status === 'success') {
        const formattedCode = res.data.data?.formatted_code
        if (formattedCode) {
          set({ code: formattedCode, lastSavedCode: formattedCode, isDirty: false })
        } else {
          set({ lastSavedCode: codeToSave, isDirty: false })
        }
        return { success: true, formattedCode }
      } else {
        return { success: false, message: res.data?.message || '保存失败' }
      }
    } catch (e: any) {
      return { success: false, message: e.message || '网络异常' }
    }
  },
})
