import { create } from 'zustand'

export type WsStatus = 'CONNECTED' | 'DISCONNECTED' | 'CONNECTING'

interface SystemState {
  wsStatus: WsStatus
  setWsStatus: (status: WsStatus) => void
  hasUnsavedChanges: boolean
  setHasUnsavedChanges: (val: boolean) => void
}

export const useSystemStore = create<SystemState>((set) => ({
  wsStatus: 'DISCONNECTED',
  setWsStatus: (status) => set({ wsStatus: status }),
  hasUnsavedChanges: false,
  setHasUnsavedChanges: (val) => set({ hasUnsavedChanges: val }),
}))