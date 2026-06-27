import React, { useContext } from 'react'
import { TerminalSquare, Trash2, Download } from 'lucide-react'
import { ChatActionContext } from './chat-context'

export function ChatHeader() {
  const { handleClearAll, handleExport } = useContext(ChatActionContext)
  return (
        <div className="h-14 border-b border-border/40 flex items-center px-6 bg-slate-50/80 dark:bg-black/40 z-10 shrink-0 backdrop-blur-md">
          <div className="flex items-center gap-2 text-primary">
            <TerminalSquare className="h-5 w-5" />
            <h2 className="font-semibold text-sm tracking-widest uppercase">AI Copilot Terminal</h2>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button onClick={handleClearAll} className="flex items-center gap-1.5 text-[10px] font-mono text-red-500 hover:text-red-400 transition-colors border border-red-500/30 bg-background hover:bg-red-500/10 px-2.5 py-1.5 rounded-md shadow-sm" title="清除所有聊天记录">
              <Trash2 className="h-3 w-3" /> 清空历史
            </button>
            <button onClick={handleExport} className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground hover:text-primary transition-colors border border-border/50 bg-background hover:bg-secondary/50 px-2.5 py-1.5 rounded-md shadow-sm" title="导出 Markdown 记录">
              <Download className="h-3 w-3" /> 导出记录
            </button>
            <div className="h-4 w-px bg-border/50" />
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">SSE CONNECTED</span>
          </div>
        </div>
  )
}