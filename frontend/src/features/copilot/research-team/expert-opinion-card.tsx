/**
 * RESEARCH-TEAM-03: 专家研判卡片（流式）
 * 每位专家一张卡，Round1/Round2 文本渐进追加。
 */
'use client'

import React from 'react'
import { cn } from '@/lib/utils'
import { expertById, biasBadge, type ExpertBias } from './expert-roster'

export interface ExpertOpinionState {
  expertId: string
  round: number
  content: string
  streaming: boolean
}

export function ExpertOpinionCard({ opinion }: { opinion: ExpertOpinionState }) {
  const profile = expertById(opinion.expertId)
  const bias: ExpertBias = profile?.bias ?? 'neutral'
  const badge = biasBadge(bias)

  return (
    <div
      className={cn(
        'rounded-xl border bg-white/5 p-3 transition-colors',
        profile?.accent ?? 'border-white/10',
        opinion.streaming && 'ring-1 ring-scene/40',
      )}
    >
      <div className="flex items-center gap-2">
        <div
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border text-xs font-bold',
            profile?.accent ?? 'border-white/20 text-slate-300',
          )}
        >
          {profile?.glyph ?? '?'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-foreground">
            {profile?.name ?? opinion.expertId}
          </div>
          <div className="text-[10px] text-muted-foreground">
            Round {opinion.round}
            {opinion.streaming && <span className="ml-1 animate-pulse text-scene">· 撰写中…</span>}
          </div>
        </div>
        <span className={cn('rounded-full border px-1.5 py-0.5 text-[10px]', badge.cls)}>
          {badge.label}
        </span>
      </div>
      <div className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-300 dark:text-slate-300">
        {opinion.content || <span className="text-muted-foreground/60">等待发言…</span>}
        {opinion.streaming && <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-scene align-middle" />}
      </div>
    </div>
  )
}
