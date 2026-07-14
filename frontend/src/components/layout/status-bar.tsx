'use client'

import { useSystemStore } from '@/stores/useSystemStore'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { MODE_META, formatModeLabel } from '@/features/trading/trading-mode-types'
import { cn } from '@/lib/utils'

/**
 * 全局底部状态栏（docs/01 §11.2）— 模式芯片与 WS 状态联动。
 * 高度约 28px，固定底栏。
 */
export function StatusBar() {
  const wsStatus = useSystemStore((s) => s.wsStatus)
  const mode = useTradingModeStore((s) => s.mode)
  const meta = MODE_META[mode]

  const wsDot =
    wsStatus === 'CONNECTED'
      ? 'bg-emerald-500'
      : wsStatus === 'CONNECTING'
        ? 'bg-amber-500 animate-pulse'
        : 'bg-red-500'

  const wsText =
    wsStatus === 'CONNECTED' ? 'Connected' : wsStatus === 'CONNECTING' ? 'Connecting' : 'Disconnected'

  return (
    <footer
      data-testid="global-status-bar"
      className="h-7 shrink-0 flex items-center gap-3 px-3 border-t border-border/40 bg-zinc-950/80 text-[10px] font-mono text-slate-400"
    >
      <span className="flex items-center gap-1.5">
        <span className={cn('h-1.5 w-1.5 rounded-full', wsDot)} aria-hidden />
        WS {wsText}
      </span>
      <span className="text-slate-600">|</span>
      <span className={cn('font-bold', meta.chipClass)} data-testid="status-bar-mode">
        [模式: {formatModeLabel(mode)}]
      </span>
    </footer>
  )
}
