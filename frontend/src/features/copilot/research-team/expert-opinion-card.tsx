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
  /** 结构化观点判断（来自后端 ExpertOpinion.data） */
  stance?: string
  confidence?: number
  keyEvidence?: string[]
  confidenceDelta?: number
  revisedStance?: string
}

const CAMP_BORDER: Record<ExpertBias, string> = {
  bullish: 'border-emerald-400/40',
  bearish: 'border-red-400/40',
  neutral: 'border-slate-400/40',
}

export function ExpertOpinionCard({ opinion, campBorder = false }: { opinion: ExpertOpinionState; campBorder?: boolean }) {
  const profile = expertById(opinion.expertId)
  const bias: ExpertBias = profile?.bias ?? 'neutral'
  const badge = biasBadge(bias)

  // 观点判断：优先用后端实际输出的 stance/confidence（动态，真实），无则回退静态 bias
  const stance = opinion.stance || opinion.revisedStance || ''
  const confidence = opinion.confidence

  // 置信度徽章（0-100 → 颜色/文案）
  const confBadge = confidence != null
    ? confidence >= 60 ? { cls: 'border-emerald-400/50 bg-emerald-400/10 text-emerald-300', label: `置信 ${confidence}` }
      : confidence <= 40 ? { cls: 'border-red-400/50 bg-red-500/10 text-red-300', label: `置信 ${confidence}` }
        : { cls: 'border-amber-400/50 bg-amber-400/10 text-amber-300', label: `置信 ${confidence}` }
    : null

  return (
    <div
      className={cn(
        'rounded-xl border bg-white/5 p-3 transition-colors',
        campBorder ? CAMP_BORDER[bias] : (profile?.accent ?? 'border-white/10'),
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
        {/* 实际置信度判断（动态，优先） */}
        {confBadge ? (
          <span className={cn('rounded-full border px-1.5 py-0.5 text-[10px] font-mono', confBadge.cls)}>
            {confBadge.label}
          </span>
        ) : (
          <span className={cn('rounded-full border px-1.5 py-0.5 text-[10px]', badge.cls)}>
            {badge.label}
          </span>
        )}
      </div>

      {/* 观点判断摘要：stance 观点 + 置信度变化 + 修正观点（结构化，独立于正文） */}
      {stance && (
        <div className="mt-2 rounded-lg border border-border/30 bg-secondary/20 px-2.5 py-1.5">
          <div className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              观点
            </span>
            <p className="text-[11px] font-medium leading-snug text-foreground/90">{stance}</p>
          </div>
          {typeof opinion.confidenceDelta === 'number' && opinion.confidenceDelta !== 0 && (
            <div className="mt-1 text-[10px] text-muted-foreground">
              置信度变化{' '}
              <span className={opinion.confidenceDelta > 0 ? 'text-emerald-400' : 'text-red-400'}>
                {opinion.confidenceDelta > 0 ? '+' : ''}{opinion.confidenceDelta}
              </span>
              {opinion.revisedStance && <span className="ml-2 text-foreground/70">→ {opinion.revisedStance}</span>}
            </div>
          )}
        </div>
      )}

      <div className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-300 dark:text-slate-300">
        {opinion.content || <span className="text-muted-foreground/60">等待发言…</span>}
        {opinion.streaming && <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-scene align-middle" />}
      </div>
    </div>
  )
}
