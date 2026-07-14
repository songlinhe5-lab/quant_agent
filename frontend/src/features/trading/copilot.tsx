'use client'

import React, { useEffect } from 'react'
import { Brain } from 'lucide-react'
import { useLayoutStore } from '@/stores/useLayoutStore'

/**
 * 深链 /copilot：打开全局抽屉并展示迁移提示（主工作区 Keep-Alive 不被替换为全页 Chat）。
 */
export function CopilotModule() {
  const openCopilot = useLayoutStore((s) => s.openCopilot)

  useEffect(() => {
    openCopilot()
  }, [openCopilot])

  return (
    <div className="flex h-[calc(100vh-100px)] w-full flex-col items-center justify-center gap-3 rounded-xl border border-border/40 bg-zinc-950/40 text-center px-6">
      <Brain className="h-8 w-8 text-violet-400" aria-hidden />
      <p className="text-sm text-slate-300">AI 副驾已迁移至全局右侧抽屉</p>
      <p className="text-xs font-mono text-slate-500">
        Cmd+Shift+A · 或点击右侧边缘把手展开 / 折叠
      </p>
      <button
        type="button"
        onClick={openCopilot}
        className="mt-2 text-xs px-3 py-1.5 rounded-md border border-violet-500/30 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 transition-colors"
      >
        打开 AI 副驾
      </button>
    </div>
  )
}
