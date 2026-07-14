'use client'

import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { TRADING_MODES, MODE_META, formatModeLabel, type TradingMode } from '@/features/trading/trading-mode-types'
import { requestTradingModeSwitch } from '@/features/trading/trading-mode-actions'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

/** 顶栏分段切换器：SANDBOX / PAPER / LIVE */
export function TradingModeSwitcher({
  className,
  alwaysShow,
}: {
  className?: string
  alwaysShow?: boolean
}) {
  const mode = useTradingModeStore((s) => s.mode)
  const { toast } = useToast()

  const onSelect = async (target: TradingMode) => {
    if (target === mode) return
    const ok = await requestTradingModeSwitch(target)
    if (ok) {
      toast({ title: '模式已切换', description: formatModeLabel(target) })
    } else if (target !== mode) {
      toast({ variant: 'destructive', title: '切换取消或失败' })
    }
  }

  return (
    <div
      data-testid="trading-mode-switcher"
      role="radiogroup"
      aria-label="交易运行模式"
      className={cn(
        alwaysShow ? 'flex' : 'hidden sm:flex',
        'items-center rounded-lg border border-slate-200 dark:border-slate-800 p-0.5 bg-slate-100/80 dark:bg-slate-900/80',
        className,
      )}
    >
      {TRADING_MODES.map((m) => {
        const active = mode === m
        const meta = MODE_META[m]
        return (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onSelect(m)}
            className={cn(
              'px-2 py-1 rounded-md text-[10px] font-bold font-mono tracking-wide transition-colors',
              active
                ? cn('bg-background shadow-sm', meta.chipClass)
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200',
            )}
            title={meta.hint}
          >
            {meta.emoji}
            {m}
          </button>
        )
      })}
    </div>
  )
}
