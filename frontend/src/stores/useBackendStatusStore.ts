import { create } from 'zustand'

/**
 * FE-NET-01: 后端可达性全局状态。
 * 仅由 api-client 在网络层失败（代理失败 / Failed to fetch / 超时）时累计失败，
 * 或在拿到任意 HTTP 响应时复位为在线。业务错误（4xx/5xx）不计入——它们说明后端在线。
 * 连续 OFFLINE_THRESHOLD 次网络层失败后判定离线，触发全局横幅。
 */

export type BackendStatus = 'online' | 'offline' | 'unknown'

interface BackendStatusState {
  status: BackendStatus
  failCount: number
  lastFailureAt: number | null
  lastError: string | null
  /** 网络层失败计数 +1；达到阈值则置为 offline */
  registerFailure: (message: string) => void
  /** 拿到任意 HTTP 响应 → 后端在线，复位计数并隐藏横幅 */
  registerSuccess: () => void
  /** 手动复位（重试按钮） */
  reset: () => void
}

const OFFLINE_THRESHOLD = 3

export const useBackendStatusStore = create<BackendStatusState>((set, get) => ({
  status: 'unknown',
  failCount: 0,
  lastFailureAt: null,
  lastError: null,

  registerFailure: (message) => {
    const failCount = get().failCount + 1
    set({
      failCount,
      lastFailureAt: Date.now(),
      lastError: message,
      status: failCount >= OFFLINE_THRESHOLD ? 'offline' : get().status,
    })
  },

  registerSuccess: () => {
    // 任何真实响应都说明后端可达；在线时仅静默复位计数，避免陈旧计数累积触发误判
    if (get().status !== 'online') {
      set({ status: 'online', failCount: 0, lastError: null, lastFailureAt: null })
    } else {
      set({ failCount: 0 })
    }
  },

  reset: () => set({ status: 'unknown', failCount: 0, lastError: null, lastFailureAt: null }),
}))
