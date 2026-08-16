/**
 * RESEARCH-TEAM-06: AI投研团队 整合视图
 * 左：阵容配置（场景/团队/自定义/轮数/命题）；右：流式会话（专家卡片 + 首席报告）。
 * 整合进 AI Copilot 抽屉的「投研团队」标签页。
 */
'use client'

import React, { useState } from 'react'
import { Play, Crown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RosterPanel, type TeamConfig } from './roster-panel'
import { TeamSession } from './team-session'

export function ResearchTeamView() {
  const [question, setQuestion] = useState('')
  const [customMode, setCustomMode] = useState(false)
  const [config, setConfig] = useState<TeamConfig>({
    scenario: 'financial_research',
    expertIds: [],
    rounds: 2,
  })
  const [runToken, setRunToken] = useState(0)
  const [running, setRunning] = useState(false)

  const canRun = question.trim().length > 0 && !running

  const onRun = () => {
    if (!canRun) return
    setRunToken((t) => t + 1)
  }

  return (
    <div className="flex h-full min-h-0">
      {/* 左：阵容配置 */}
      <div className="flex w-[44%] shrink-0 flex-col border-r border-border/40">
        <div className="flex-1 overflow-y-auto p-3">
          <RosterPanel
            question={question}
            onQuestionChange={setQuestion}
            config={config}
            onConfigChange={setConfig}
            customMode={customMode}
            onCustomModeChange={setCustomMode}
          />
        </div>
        <div className="border-t border-border/40 p-2">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun}
            className={cn(
              'flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors',
              canRun
                ? 'bg-scene text-white hover:bg-scene/90'
                : 'cursor-not-allowed bg-white/5 text-muted-foreground',
            )}
          >
            {running ? <Crown className="h-3.5 w-3.5 animate-pulse" /> : <Play className="h-3.5 w-3.5" />}
            {running ? '投研会进行中…' : '发起投研会'}
          </button>
        </div>
      </div>

      {/* 右：会话流 */}
      <div className="min-w-0 flex-1">
        <TeamSession
          question={question}
          config={config}
          customMode={customMode}
          runToken={runToken}
          onRunningChange={setRunning}
        />
      </div>
    </div>
  )
}
