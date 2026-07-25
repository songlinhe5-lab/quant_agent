import type { Time } from 'lightweight-charts'

// PROD-12: 跨图表十字线同步管理器（单例）
// 分屏/对比模式下，多个 K 线图共享同一 syncGroup，移动任一图的十字线时，
// 同组其他图会同步显示对应时间位置的十字线（同一标的不同周期 / 不同标的同一时间）。

export interface CrosshairSyncPosition {
  time: Time | null
  price: number | null
}

type ApplyFn = (pos: CrosshairSyncPosition) => void

class CrosshairSyncManager {
  private groups = new Map<string, Map<string, ApplyFn>>()

  register(group: string, id: string, fn: ApplyFn) {
    if (!this.groups.has(group)) this.groups.set(group, new Map())
    this.groups.get(group)!.set(id, fn)
  }

  unregister(group: string, id: string) {
    const g = this.groups.get(group)
    if (!g) return
    g.delete(id)
    if (g.size === 0) this.groups.delete(group)
  }

  // 由 sourceId 所属图表广播当前十字线位置，同组其他图表收到后应用
  broadcast(sourceId: string, group: string, pos: CrosshairSyncPosition) {
    const g = this.groups.get(group)
    if (!g) return
    g.forEach((fn, id) => {
      if (id !== sourceId) fn(pos)
    })
  }
}

export const crosshairSync = new CrosshairSyncManager()
