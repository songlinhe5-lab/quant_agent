/**
 * STRAT-01a: Layout Slice — 策略浏览器 / 侧栏 / 工作区 Tab
 */
import { StateCreator } from 'zustand'
import { apiClient } from '@/lib/api-client'
import type { StrategyStore } from '../index'

export interface LayoutSlice {
  // Strategy Explorer
  activeStrategy: string
  setActiveStrategy: (name: string) => void
  strategies: any[]
  setStrategies: (list: any[]) => void
  favorites: string[]
  setFavorites: (favs: string[]) => void
  fetchStrategies: () => Promise<void>

  // Layout
  leftSidebarOpen: boolean
  rightSidebarOpen: boolean
  activeWorkspaceTab: 'code' | 'report'
  setWorkspaceTab: (tab: 'code' | 'report') => void
}

export const createLayoutSlice: StateCreator<StrategyStore, [], [], LayoutSlice> = (set) => ({
  // Strategy Explorer
  activeStrategy: '',
  setActiveStrategy: (activeStrategy) => set({ activeStrategy }),
  strategies: [],
  setStrategies: (strategies) => set({ strategies }),
  favorites: [],
  setFavorites: (favorites) => set({ favorites }),
  fetchStrategies: async () => {
    try {
      const res = await apiClient.get('/strategy/list')
      if (res.data?.status === 'success') {
        set({ strategies: res.data.data })
      }
    } catch (e) {
      console.error('Failed to fetch strategies:', e)
    }
  },

  // Layout
  leftSidebarOpen: true,
  rightSidebarOpen: true,
  activeWorkspaceTab: 'code',
  setWorkspaceTab: (tab) => set({ activeWorkspaceTab: tab }),
})
