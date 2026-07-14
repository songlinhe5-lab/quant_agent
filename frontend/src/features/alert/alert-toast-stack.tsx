'use client'

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, ExternalLink, X } from 'lucide-react'
import { useAlertOverlayStore } from '@/stores/useAlertOverlayStore'
import { applyAlertNavigation } from './alert-nav'
import { cn } from '@/lib/utils'
import type { AlertPushPayload } from '@/types/alert'

/** P1~P2 右上角 Toast 栈（不阻断操作） */
export function AlertToastStack() {
  const stack = useAlertOverlayStore((s) => s.toastStack)
  const dismissToast = useAlertOverlayStore((s) => s.dismissToast)
  const navigate = useNavigate()

  return (
    <div
      data-testid="alert-toast-stack"
      className="fixed top-16 right-4 z-[150] flex flex-col gap-2 w-[min(100vw-2rem,360px)] pointer-events-none"
    >
      {stack.map((item) => (
        <AlertToastCard
          key={item.event_id}
          item={item}
          onDismiss={() => dismissToast(item.event_id)}
          onNavigate={() => {
            applyAlertNavigation(navigate, item.ui_hint, item.ticker)
            dismissToast(item.event_id)
          }}
        />
      ))}
    </div>
  )
}

function AlertToastCard({
  item,
  onDismiss,
  onNavigate,
}: {
  item: AlertPushPayload
  onDismiss: () => void
  onNavigate: () => void
}) {
  const duration = typeof item.ui_hint?.duration === 'number' ? item.ui_hint.duration : 8000

  useEffect(() => {
    if (item.priority === 'p0') return
    const t = setTimeout(onDismiss, duration)
    return () => clearTimeout(t)
  }, [item.event_id, item.priority, duration, onDismiss])

  const isP1 = item.priority === 'p1'

  return (
    <div
      className={cn(
        'pointer-events-auto rounded-lg border backdrop-blur-md shadow-lg p-3',
        'animate-in slide-in-from-right-4 fade-in duration-200',
        isP1
          ? 'bg-amber-950/90 border-amber-500/40 text-amber-100'
          : 'bg-zinc-900/95 border-white/10 text-slate-200',
      )}
      role="status"
    >
      <div className="flex items-start gap-2">
        <Bell className={cn('h-4 w-4 shrink-0 mt-0.5', isP1 ? 'text-amber-400' : 'text-slate-400')} />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-mono font-bold uppercase opacity-70">
            {item.priority.toUpperCase()}
            {item.ticker ? ` · ${item.ticker}` : ''}
          </p>
          <p className="text-xs font-semibold mt-0.5 line-clamp-2">{item.message}</p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="p-0.5 rounded hover:bg-white/10 text-slate-400"
          aria-label="关闭"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {(item.ui_hint?.route || item.ui_hint?.symbol || item.ticker) && (
        <button
          type="button"
          onClick={onNavigate}
          className="mt-2 inline-flex items-center gap-1 text-[10px] font-bold text-sky-400 hover:text-sky-300"
        >
          <ExternalLink className="h-3 w-3" />
          查看行情
        </button>
      )}
    </div>
  )
}
