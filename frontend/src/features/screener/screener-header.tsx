'use client'

import React from 'react'
import { Database, Settings2 } from 'lucide-react'
import { useScreenerContext } from './screener-context'

export function ScreenerHeader() {
  const { setShowRagDict, setShowSubManager } = useScreenerContext()
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-1.5 rounded-full bg-violet-500 dark:bg-violet-400 transition-colors duration-300" aria-hidden="true" />
      <h1 className="text-base font-bold tracking-tight">智能量化选股</h1>
      <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Agentic Screener</span>
      <div className="ml-auto flex items-center gap-2">
        <button onClick={() => setShowRagDict(true)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Database className="h-3.5 w-3.5" />RAG 词库</button>
        <button onClick={() => setShowSubManager(true)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors bg-secondary/30 hover:bg-secondary/60 px-3 py-1.5 rounded-lg border border-border/50 shadow-sm">
          <Settings2 className="h-3.5 w-3.5" />管理订阅</button>
      </div>
    </div>
  )
}