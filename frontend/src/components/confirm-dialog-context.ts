/**
 * SEC-09: 全局确认弹窗上下文与函数式 API
 * 与 ConfirmDialogProvider（组件）分离，避免 react-refresh fast-refresh 警告
 * （组件文件只应导出组件，否则 dev HMR 会丢失状态）。
 *
 * 使用方式：
 *   1. 在 App 根组件中放置 <ConfirmDialogProvider />
 *   2. 在任意位置调用 const ok = await confirmDanger('标题', '描述')
 */
import { createContext, useContext } from 'react'

export interface ConfirmContextValue {
  confirm: (opts: {
    title: string
    description: string
    confirmLabel?: string
    cancelLabel?: string
    destructive?: boolean
    requireInputConfirm?: string
  }) => Promise<boolean>
}

export const ConfirmContext = createContext<ConfirmContextValue | null>(null)

/**
 * 确认弹窗 Hook — 必须在 ConfirmDialogProvider 内部使用
 */
export function useConfirmDialog() {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirmDialog 必须在 ConfirmDialogProvider 内部使用')
  return ctx
}

// ── 全局函数式 API ──────────────────────────────────────────────────────────────
// 通过模块级引用，允许在非组件代码（如事件回调）中调用确认弹窗

let globalConfirm: ConfirmContextValue['confirm'] | null = null

/**
 * 注册全局 confirm 函数（由 ConfirmDialogProvider 内部自动调用）
 */
export function registerGlobalConfirm(fn: ConfirmContextValue['confirm']) {
  globalConfirm = fn
}

/**
 * 全局确认弹窗（可在任意上下文中调用，替代 window.confirm）
 * @returns Promise<boolean> — 用户点击确认返回 true，取消返回 false
 */
export async function confirmDanger(
  title: string,
  description: string,
  opts?: { confirmLabel?: string; cancelLabel?: string; requireInputConfirm?: string },
): Promise<boolean> {
  if (!globalConfirm) {
    // 降级：如果 Provider 未挂载，回退到原生 confirm
    return window.confirm(`${title}\n\n${description}`)
  }
  return globalConfirm({
    title,
    description,
    confirmLabel: opts?.confirmLabel || '确认',
    cancelLabel: opts?.cancelLabel || '取消',
    destructive: true,
    requireInputConfirm: opts?.requireInputConfirm,
  })
}
