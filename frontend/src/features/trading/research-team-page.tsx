'use client'

import { Users } from 'lucide-react'
import { ResearchTeamView } from '@/features/copilot/research-team/research-team-view'

/**
 * COPILOT-06: 投研会宽屏页——从 520px 抽屉迁至左导航「投研」域全宽。
 * 左侧导航 entry: /research-team
 */
export function ResearchTeamPage() {
  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-border/40 bg-card">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border/30 px-4">
        <Users className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-semibold tracking-wide text-foreground">AI 投研会</h1>
        <span className="ml-auto text-[10px] text-muted-foreground">17 专家 · 6 团队 · 多轮辩论 · 首席收敛</span>
      </div>
      {/* 内容区填满剩余高度，滚动仅发生在内部 TeamSession / SessionDetailView，避免外层页面滚动与内层面板滚动冲突 */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <ResearchTeamView />
      </div>
    </div>
  )
}
