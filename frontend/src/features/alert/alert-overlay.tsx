'use client'

import { AlertTriangle, ExternalLink, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAlertOverlayStore, currentP0 } from '@/stores/useAlertOverlayStore'
import { applyAlertNavigation } from './alert-nav'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'

/**
 * FE-PROD-03 · P0 全屏不可关闭浮层（仅「查看详情」「全部已读」可解除）
 */
export function AlertOverlay() {
  const navigate = useNavigate()
  const p0 = useAlertOverlayStore((s) => currentP0(s))
  const p0Queue = useAlertOverlayStore((s) => s.p0Queue)
  const dismissP0 = useAlertOverlayStore((s) => s.dismissP0)
  const clearP0Queue = useAlertOverlayStore((s) => s.clearP0Queue)

  if (!p0) return null

  const onViewDetails = () => {
    applyAlertNavigation(navigate, p0.ui_hint, p0.ticker)
    // 查看详情不自动 ack，保留队首直至全部已读；若 hint 指向行情则仍可返回 Overlay
  }

  const onAckAll = async () => {
    const ids = p0Queue.map((e) => e.event_id)
    await Promise.allSettled(ids.map((id) => apiClient.post(`/alert/events/${id}/ack`)))
    clearP0Queue()
  }

  const onAckCurrent = async () => {
    try {
      await apiClient.post(`/alert/events/${p0.event_id}/ack`)
    } catch {
      /* 仍允许本地清除，避免卡死 */
    }
    dismissP0(p0.event_id)
  }

  return (
    <div
      data-testid="alert-overlay-p0"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="alert-overlay-title"
      className={cn(
        'fixed inset-0 z-[200] flex items-center justify-center',
        'bg-red-950/90 backdrop-blur-md',
        p0.ui_hint?.flash !== false && 'animate-[pulse_1.5s_ease-in-out_infinite]',
      )}
      // 阻断 Esc / 点击背景关闭
      onKeyDown={(e) => {
        if (e.key === 'Escape') e.stopPropagation()
      }}
    >
      <div
        className={cn(
          'relative mx-4 w-full max-w-lg rounded-xl border-2 border-red-500/60',
          'bg-zinc-950/95 p-6 shadow-[0_0_40px_rgba(239,68,68,0.35)]',
          'animate-none', // 内容区不脉冲，避免阅读困难
        )}
        style={{ animation: 'none' }}
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-8 w-8 text-red-500 shrink-0 mt-0.5" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-mono font-bold tracking-widest text-red-400 uppercase mb-1">
              P0 Critical · {p0Queue.length > 1 ? `${p0Queue.length} pending` : 'Ack required'}
            </p>
            <h2 id="alert-overlay-title" className="text-lg font-bold text-red-100 truncate">
              {p0.ticker ? `${p0.ticker} · ` : ''}
              {p0.message}
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              来源: {p0.source} ·{' '}
              {new Date(p0.triggered_at * 1000).toLocaleString('zh-CN', { hour12: false })}
            </p>
            {p0Queue.length > 1 && (
              <p className="mt-1 text-xs text-amber-500 font-mono">
                另有 {p0Queue.length - 1} 条未确认 P0（全部已读将一并确认）
              </p>
            )}
          </div>
        </div>

        <div className="mt-6 flex flex-wrap gap-2 justify-end">
          <button
            type="button"
            onClick={onViewDetails}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md border border-red-500/40 text-red-200 text-xs font-bold hover:bg-red-500/15 transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            查看详情
          </button>
          <button
            type="button"
            onClick={onAckCurrent}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md border border-white/10 text-slate-300 text-xs font-bold hover:bg-white/5 transition-colors"
          >
            本条已读
          </button>
          <button
            type="button"
            onClick={onAckAll}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-red-600 text-white text-xs font-bold hover:bg-red-500 transition-colors"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            全部已读
          </button>
        </div>
      </div>
    </div>
  )
}
