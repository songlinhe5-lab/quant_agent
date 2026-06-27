/**
 * SEC-09: 全局确认弹窗系统
 * 替代原生 window.confirm，提供统一的暗黑风格二次确认 UI。
 * 使用方式：
 *   1. 在 App 根组件中放置 <ConfirmDialogProvider />
 *   2. 在任意位置调用 const ok = await confirmDanger('标题', '描述')
 */
import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { AlertTriangle } from 'lucide-react'

interface ConfirmState {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  cancelLabel: string
  destructive: boolean
}

const DEFAULT_STATE: ConfirmState = {
  open: false,
  title: '',
  description: '',
  confirmLabel: '确认',
  cancelLabel: '取消',
  destructive: true,
}

interface ConfirmContextValue {
  confirm: (opts: {
    title: string
    description: string
    confirmLabel?: string
    cancelLabel?: string
    destructive?: boolean
  }) => Promise<boolean>
}

const ConfirmContext = createContext<ConfirmContextValue | null>(null)

/**
 * 确认弹窗 Hook — 必须在 ConfirmDialogProvider 内部使用
 */
export function useConfirmDialog() {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirmDialog 必须在 ConfirmDialogProvider 内部使用')
  return ctx
}

/**
 * 全局确认弹窗 Provider — 放在 App 根组件中
 */
export function ConfirmDialogProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConfirmState>(DEFAULT_STATE)
  const resolveRef = useRef<((value: boolean) => void) | null>(null)

  const confirm = useCallback((opts: {
    title: string
    description: string
    confirmLabel?: string
    cancelLabel?: string
    destructive?: boolean
  }) => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve
      setState({
        open: true,
        title: opts.title,
        description: opts.description,
        confirmLabel: opts.confirmLabel || '确认',
        cancelLabel: opts.cancelLabel || '取消',
        destructive: opts.destructive !== false,
      })
    })
  }, [])

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true)
    resolveRef.current = null
    setState(DEFAULT_STATE)
  }, [])

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false)
    resolveRef.current = null
    setState(DEFAULT_STATE)
  }, [])

  // 自动注册全局 confirm API，允许非组件代码调用
  useEffect(() => {
    registerGlobalConfirm(confirm)
  }, [confirm])

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      <AlertDialog open={state.open} onOpenChange={(open) => { if (!open) handleCancel() }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              {state.destructive && <AlertTriangle className="h-5 w-5 text-red-500 shrink-0" />}
              {state.title}
            </AlertDialogTitle>
            <AlertDialogDescription>{state.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancel}>{state.cancelLabel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirm}
              className={state.destructive ? 'bg-red-600 hover:bg-red-700 text-white' : ''}
            >
              {state.confirmLabel}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  )
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
  opts?: { confirmLabel?: string; cancelLabel?: string }
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
  })
}
