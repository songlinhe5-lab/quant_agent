import { create } from 'zustand'
import type { AlertPushPayload, NotificationPriority } from '@/types/alert'

const TOAST_CAP = 5

interface AlertOverlayState {
  /** 未确认的 P0 队列（先进先出展示队首） */
  p0Queue: AlertPushPayload[]
  /** P1/P2 Toast 栈 */
  toastStack: AlertPushPayload[]
  /** 顶栏 🔔 未读角标（P0+P1 推送累计，进告警中心可清） */
  badgeCount: number
  /** Alert WS 断连 → 告警历史 STALE */
  wsStale: boolean
  enqueuePush: (payload: AlertPushPayload) => void
  dismissP0: (eventId: string) => void
  clearP0Queue: () => void
  dismissToast: (eventId: string) => void
  clearBadge: () => void
  setWsStale: (stale: boolean) => void
}

function priorityOf(p: AlertPushPayload): NotificationPriority {
  return p.priority || 'p3'
}

export const useAlertOverlayStore = create<AlertOverlayState>((set, get) => ({
  p0Queue: [],
  toastStack: [],
  badgeCount: 0,
  wsStale: false,

  enqueuePush: (payload) => {
    const pri = priorityOf(payload)
    if (pri === 'p0') {
      set((s) => ({
        p0Queue: s.p0Queue.some((e) => e.event_id === payload.event_id)
          ? s.p0Queue
          : [...s.p0Queue, payload],
        badgeCount: s.badgeCount + 1,
      }))
      return
    }
    if (pri === 'p1' || pri === 'p2') {
      set((s) => ({
        toastStack: [payload, ...s.toastStack.filter((e) => e.event_id !== payload.event_id)].slice(
          0,
          TOAST_CAP,
        ),
        badgeCount: pri === 'p1' ? s.badgeCount + 1 : s.badgeCount,
      }))
      return
    }
    // p3: 仅角标
    set((s) => ({ badgeCount: s.badgeCount + 1 }))
  },

  dismissP0: (eventId) =>
    set((s) => ({ p0Queue: s.p0Queue.filter((e) => e.event_id !== eventId) })),

  clearP0Queue: () => set({ p0Queue: [] }),

  dismissToast: (eventId) =>
    set((s) => ({ toastStack: s.toastStack.filter((e) => e.event_id !== eventId) })),

  clearBadge: () => set({ badgeCount: 0 }),

  setWsStale: (wsStale) => set({ wsStale }),
}))

export function currentP0(state: AlertOverlayState): AlertPushPayload | null {
  return state.p0Queue[0] ?? null
}
