'use client'

import { StrategyIDE } from '@/features/strategy/layout/strategy-ide'

export function StrategyPage() {
  return (
    <div className="space-y-4 animate-in fade-in duration-500">
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-violet-500 dark:bg-violet-400 transition-colors duration-300" aria-hidden="true" />
        <h1 className="text-base font-bold tracking-tight">策略研发工作台</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          Strategy IDE · Copilot
        </span>
      </div>
      <StrategyIDE />
    </div>
  )
}