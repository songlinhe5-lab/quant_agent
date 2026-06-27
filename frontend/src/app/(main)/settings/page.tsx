import React from 'react'
import { Settings } from 'lucide-react'

export default function SettingsPage() {
  return (
    <div className="space-y-4">
      {/* 标题栏 */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-slate-500 dark:bg-slate-400" />
        <h1 className="text-base font-bold tracking-tight">系统全局设置</h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          System Settings
        </span>
      </div>
      
      <div className="glass-card rounded-xl border border-border/40 flex items-center justify-center min-h-[500px] h-[calc(100vh-140px)] shadow-sm">
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <Settings className="h-8 w-8 animate-[spin_4s_linear_infinite] opacity-50" />
          <p className="text-sm font-mono">⚙️ 全局设置模块开发中...</p>
        </div>
      </div>
    </div>
  )
}