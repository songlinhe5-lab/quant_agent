/**
 * SEC-09: 全局确认弹窗系统
 * 替代原生 window.confirm，提供统一的暗黑风格二次确认 UI。
 * 使用方式：
 *   1. 在 App 根组件中放置 <ConfirmDialogProvider />
 *   2. 在任意位置调用 const ok = await confirmDanger('标题', '描述')
 */
import React, { useState, useCallback, useRef, useEffect } from 'react'
import { ConfirmContext, registerGlobalConfirm } from '@/components/confirm-dialog-context'
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
  requireInputConfirm: string | null
  inputValue: string
}

const DEFAULT_STATE: ConfirmState = {
  open: false,
  title: '',
  description: '',
  confirmLabel: '确认',
  cancelLabel: '取消',
  destructive: true,
  requireInputConfirm: null,
  inputValue: '',
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
    requireInputConfirm?: string
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
        requireInputConfirm: opts.requireInputConfirm || null,
        inputValue: '',
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
          {state.requireInputConfirm && (
            <div className="py-2">
              <label className="text-xs text-muted-foreground mb-1.5 block">
                请输入 <span className="font-mono font-bold text-foreground">{state.requireInputConfirm}</span> 以确认操作
              </label>
              <input
                type="text"
                value={state.inputValue}
                onChange={(e) => setState(prev => ({ ...prev, inputValue: e.target.value }))}
                className="w-full bg-background border border-border/50 rounded-md px-3 py-2 text-sm font-mono outline-none focus:border-red-500 transition-colors"
                placeholder={state.requireInputConfirm}
                autoFocus
              />
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancel}>{state.cancelLabel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirm}
              disabled={state.requireInputConfirm !== null && state.inputValue !== state.requireInputConfirm}
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
