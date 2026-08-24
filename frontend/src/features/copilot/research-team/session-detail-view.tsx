/**
 * 历史投研会详情视图：渲染单个历史会话的完整辩论记录。
 * 全量时间线：按轮次分组同屏展示所有专家意见 + 首席最终报告（与新会话视图同构）。
 */
'use client'

import React from 'react'
import { Crown, Inbox } from 'lucide-react'
import { ChiefReportPanel } from './chief-report-panel'
import { ExpertOpinionCard, type ExpertOpinionState } from './expert-opinion-card'
import { expertById } from './expert-roster'
import type { SessionDetail, HistoricalOpinion } from './expert-team-client'

/** 把后端 HistoricalOpinion 映射成前端 ExpertOpinionState（reasoning 作为正文 content） */
function toOpinionState(o: HistoricalOpinion): ExpertOpinionState {
  return {
    expertId: o.expert_id,
    round: o.round,
    content: o.reasoning || o.stance || '',
    streaming: false,
    stance: o.stance,
    confidence: o.confidence,
    keyEvidence: o.key_evidence,
    confidenceDelta: o.confidence_delta,
    revisedStance: o.revised_stance,
  }
}

export function SessionDetailView({ session }: { session: SessionDetail }) {
  // 合并全部轮次意见（按阵容顺序、轮次顺序全量展示）
  const allOpinions = [
    ...(session.round1_opinions ?? []),
    ...(session.round2_opinions ?? []),
  ].map(toOpinionState)
  const expertIds = Array.from(new Set(allOpinions.map((o) => o.expertId)))
  const rounds = Array.from(new Set(allOpinions.map((o) => o.round))).sort((a, b) => a - b)
  const chief = session.chief_report

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 顶部：会话信息 */}
      <div className="flex items-center gap-2 border-b border-border/40 px-3 py-2">
        <Crown className="h-3.5 w-3.5 text-yellow-300" />
        <span className="text-[11px] font-semibold text-foreground">历史投研会</span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground" title={session.question}>
          {session.question}
        </span>
      </div>

      {/* 滚动内容区：按轮次分组的全量时间线 */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {expertIds.length === 0 && !chief ? (
          <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
            <Inbox className="mb-2 h-8 w-8 opacity-40" />
            <p className="text-xs">该记录暂无辩论内容</p>
          </div>
        ) : (
          <>
            {rounds.map((r) => {
              const roundOps = allOpinions.filter((o) => o.round === r)
              const orderedOps = [...roundOps].sort(
                (a, b) => expertIds.indexOf(a.expertId) - expertIds.indexOf(b.expertId),
              )
              const servedIds = new Set(roundOps.map((o) => o.expertId))
              const missingExperts = expertIds.filter((eid) => !servedIds.has(eid))
              return (
                <div key={r} className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    第 {r} 轮 · {r === 1 ? '独立研判' : '交叉辩论'}
                    <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/60">
                      {roundOps.length}/{expertIds.length} 位专家已发言
                    </span>
                  </div>
                  {orderedOps.map((o, i) => (
                    <ExpertOpinionCard key={`${o.expertId}-${o.round}-${i}`} opinion={o} campBorder />
                  ))}
                  {missingExperts.map((eid) => {
                    const p = expertById(eid)
                    return (
                      <div
                        key={eid}
                        className="flex items-center gap-2 rounded-xl border border-border/30 bg-white/[0.02] px-3 py-2 text-[11px] text-muted-foreground"
                      >
                        <span className="text-xs">{p?.glyph ?? '🧑'}</span>
                        <span>{p?.name ?? eid}</span>
                        <span className="text-muted-foreground/60">本轮未产出观点</span>
                      </div>
                    )
                  })}
                </div>
              )
            })}

            {/* 首席投资官收敛报告（与新会话面板同构） */}
            {chief && (
              <ChiefReportPanel report={{
                probability: chief.probability_assessment,
                body: chief.full_report,
                finalRecommendation: chief.final_recommendation,
                consensusAreas: chief.consensus_areas,
                divergenceAreas: chief.divergence_areas,
                strongestBullCase: chief.strongest_bull_case,
                strongestBearCase: chief.strongest_bear_case,
                riskWarnings: chief.risk_warnings,
                minorityOpinion: chief.minority_opinion,
              }} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
