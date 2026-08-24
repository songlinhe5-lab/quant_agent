/**
 * 历史投研会详情视图：渲染单个历史会话的完整辩论记录。
 * 左：角色 tab（逐个专家查看其全部轮次意见）
 * 下：首席最终报告
 */
'use client'

import React, { useState } from 'react'
import { Crown, Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'
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
  // 合并全部轮次意见
  const allOpinions = [
    ...(session.round1_opinions ?? []),
    ...(session.round2_opinions ?? []),
  ].map(toOpinionState)
  const expertList = Array.from(new Set(allOpinions.map((o) => o.expertId)))
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const activeExpert = (activeTab && activeTab !== '__cio__') ? activeTab : (expertList[0] ?? null)
  const activeOpinions = activeExpert ? allOpinions.filter((o) => o.expertId === activeExpert) : []
  const chief = session.chief_report
  const showCioTab = !!chief

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

      {/* 滚动内容区 */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {expertList.length === 0 && !chief ? (
          <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
            <Inbox className="mb-2 h-8 w-8 opacity-40" />
            <p className="text-xs">该记录暂无辩论内容</p>
          </div>
        ) : (
          <>
            {/* 角色 tab 栏（含首席投资官） */}
            {expertList.length > 0 && (
              <div className="flex gap-1 overflow-x-auto pb-1">
                {expertList.map((eid) => {
                  const p = expertById(eid)
                  const isActive = eid === activeTab
                  const rounds = allOpinions.filter((o) => o.expertId === eid)
                  return (
                    <button
                      key={eid}
                      type="button"
                      onClick={() => setActiveTab(eid)}
                      className={cn(
                        'flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] transition-colors',
                        isActive
                          ? 'border-scene/50 bg-scene/15 text-foreground'
                          : 'border-border/40 text-muted-foreground hover:bg-secondary/40 hover:text-foreground',
                      )}
                    >
                      <span className="text-xs">{p?.glyph ?? '🧑'}</span>
                      <span className="max-w-[90px] truncate">{p?.name ?? eid}</span>
                      <span className="text-[10px] text-muted-foreground/70">R{rounds.length}</span>
                    </button>
                  )
                })}
                {showCioTab && (
                  <button
                    type="button"
                    onClick={() => setActiveTab('__cio__')}
                    className={cn(
                      'flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] transition-colors',
                      activeTab === '__cio__'
                        ? 'border-yellow-300/50 bg-yellow-300/15 text-yellow-300'
                        : 'border-yellow-300/30 text-yellow-300/70 hover:bg-yellow-300/10',
                    )}
                  >
                    <Crown className="h-3 w-3" />
                    <span className="max-w-[90px] truncate">首席投资官</span>
                  </button>
                )}
              </div>
            )}

            {/* 当前选中专家意见 */}
            {activeTab !== '__cio__' && activeOpinions.map((o, i) => (
              <ExpertOpinionCard key={`${o.expertId}-${o.round}-${i}`} opinion={o} campBorder />
            ))}

            {/* 首席投资官 tab 内容：结构化收敛报告（与新会话面板同构） */}
            {activeTab === '__cio__' && chief && (
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
