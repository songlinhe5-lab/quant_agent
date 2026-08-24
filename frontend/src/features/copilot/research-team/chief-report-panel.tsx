/**
 * RESEARCH-TEAM-06: 首席投资官最终研判面板
 * 统一渲染结构化收敛报告（共识/分歧/多空论据/风险/少数派 + Markdown 正文），
 * 供新会话流式态（team-session）与历史会话（session-detail-view）复用。
 */
'use client'

import React from 'react'
import { Crown, AlertTriangle, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BriefingMarkdown } from '@/features/briefing/briefing-markdown'

export interface ChiefReportView {
  /** 看涨概率 0-100 */
  probability?: number
  /** Markdown 正文（新会话流式拼接的 content / 历史会话的 full_report） */
  body?: string
  /** 正文缺失时的兜底（final_recommendation） */
  finalRecommendation?: string
  consensusAreas?: string[]
  divergenceAreas?: string[]
  strongestBullCase?: string
  strongestBearCase?: string
  riskWarnings?: string[]
  minorityOpinion?: string
}

function Block({ title, items, cls }: { title: string; items: string[]; cls: string }) {
  if (!items.length) return null
  return (
    <div className="rounded-lg border border-border/30 bg-white/[0.02] p-2">
      <div className={cn('mb-1 text-[10px] font-medium', cls)}>{title}</div>
      <ul className="space-y-0.5">
        {items.map((it, i) => (
          <li key={i} className="flex gap-1.5 text-[11px] leading-relaxed text-foreground/80">
            <span className="mt-0.5 shrink-0 text-muted-foreground/60">·</span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ChiefReportPanel({ report }: { report: ChiefReportView }) {
  const body = report.body || report.finalRecommendation || ''
  return (
    <div className="rounded-xl border border-yellow-300/40 bg-yellow-300/5 p-3">
      <div className="mb-2 flex items-center gap-2">
        <Crown className="h-4 w-4 text-yellow-300" />
        <span className="text-xs font-bold text-yellow-300">首席投资官 · 最终研判</span>
        {typeof report.probability === 'number' && (
          <span className="ml-auto rounded-full border border-scene/40 bg-scene/10 px-2 py-0.5 text-[10px] text-scene">
            看涨概率 {report.probability}%
          </span>
        )}
      </div>

      {/* 结构化收敛模块：共识 / 分歧 / 多空最强论据 / 风险 / 少数派 */}
      {(report.consensusAreas?.length || report.divergenceAreas?.length) ? (
        <div className="mb-2 grid grid-cols-2 gap-2">
          <Block title="共识区" items={report.consensusAreas ?? []} cls="text-emerald-400" />
          <Block title="分歧区" items={report.divergenceAreas ?? []} cls="text-amber-500" />
        </div>
      ) : null}

      {(report.strongestBullCase || report.strongestBearCase) && (
        <div className="mb-2 grid grid-cols-2 gap-2">
          {report.strongestBullCase && (
            <div className="rounded-lg border border-emerald-400/20 bg-emerald-500/5 p-2">
              <div className="mb-1 text-[10px] font-medium text-emerald-400">最强看多论据</div>
              <p className="text-[11px] leading-relaxed text-foreground/80">{report.strongestBullCase}</p>
            </div>
          )}
          {report.strongestBearCase && (
            <div className="rounded-lg border border-red-400/20 bg-red-500/5 p-2">
              <div className="mb-1 text-[10px] font-medium text-red-400">最强看空论据</div>
              <p className="text-[11px] leading-relaxed text-foreground/80">{report.strongestBearCase}</p>
            </div>
          )}
        </div>
      )}

      {!!report.riskWarnings?.length && (
        <div className="mb-2 rounded-lg border border-amber-500/25 bg-amber-500/5 p-2">
          <div className="mb-1 flex items-center gap-1 text-[10px] font-medium text-amber-500">
            <AlertTriangle className="h-3 w-3" /> 风险提示
          </div>
          <ul className="space-y-0.5">
            {report.riskWarnings.map((w, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-foreground/80">· {w}</li>
            ))}
          </ul>
        </div>
      )}

      {report.minorityOpinion && (
        <div className="mb-2 rounded-lg border border-border/30 bg-white/[0.02] p-2">
          <div className="mb-1 flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
            <Users className="h-3 w-3" /> 少数派意见保留
          </div>
          <p className="text-[11px] leading-relaxed text-foreground/70">{report.minorityOpinion}</p>
        </div>
      )}

      {/* Markdown 正文 */}
      {body && <BriefingMarkdown content={body} />}
    </div>
  )
}
