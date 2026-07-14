'use client'

import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { MODE_META, formatModeLabel } from '@/features/trading/trading-mode-types'
import { cn } from '@/lib/utils'
import { ShieldAlert, ShieldCheck, ScrollText } from 'lucide-react'
import { requestTradingModeSwitch } from '@/features/trading/trading-mode-actions'
import { useToast } from '@/hooks/use-toast'

/** 全局常驻模式横幅（Navbar 下方）；LIVE 脉冲、不可关闭语义 */
export function TradingModeBanner() {
  const mode = useTradingModeStore((s) => s.mode)
  const meta = MODE_META[mode]
  const { toast } = useToast()

  const Icon = mode === 'LIVE' ? ShieldAlert : mode === 'PAPER' ? ScrollText : ShieldCheck

  const onSwitchClick = async () => {
    const next = mode === 'LIVE' ? 'PAPER' : mode === 'PAPER' ? 'SANDBOX' : 'PAPER'
    const ok = await requestTradingModeSwitch(next)
    if (ok) {
      toast({ title: '模式已切换', description: formatModeLabel(next) })
    } else {
      toast({ variant: 'destructive', title: '切换取消或失败' })
    }
  }

  return (
    <div
      data-testid="trading-mode-banner"
      role="status"
      aria-live="polite"
      className={cn(
        'flex-shrink-0 px-4 py-1.5 flex items-center justify-between border-b text-xs font-bold transition-colors',
        meta.bannerClass,
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <Icon className="w-3.5 h-3.5 shrink-0" aria-hidden />
        <span className="truncate">
          {meta.emoji} {meta.label} — {meta.hint}
        </span>
      </div>
      <button
        type="button"
        onClick={onSwitchClick}
        className="shrink-0 ml-3 px-2 py-0.5 rounded border border-current/30 hover:bg-current/10 transition-colors text-[10px]"
      >
        切换模式
      </button>
    </div>
  )
}
