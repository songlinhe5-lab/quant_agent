/**
 * RESEARCH-TEAM-05: 投研团队会话视图
 * 接收配置 → 发起 SSE → 流式渲染专家 Round1/Round2 卡片 → 首席最终报告。
 */
'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Crown, AlertTriangle, Square, Database, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BriefingMarkdown } from '@/features/briefing/briefing-markdown'
import { ExpertOpinionCard, type ExpertOpinionState } from './expert-opinion-card'
import { expertById } from './expert-roster'
import {
  startTeamAnalysis,
  type TeamStreamEvent,
  type ChiefReportEvent,
  type ExpertOpinionData,
} from './expert-team-client'
import type { TeamConfig } from './roster-panel'

interface TeamSessionProps {
  question: string
  config: TeamConfig
  customMode: boolean
  /** 触发运行：递增的 runToken 改变即发起一次新分析 */
  runToken: number
  onRunningChange?: (running: boolean) => void
}

type Phase = 'idle' | 'running' | 'done' | 'error'

export function TeamSession({ question, config, customMode, runToken, onRunningChange }: TeamSessionProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [statusText, setStatusText] = useState('')
  const [opinions, setOpinions] = useState<ExpertOpinionState[]>([])
  const [currentRound, setCurrentRound] = useState(0)
  const [chief, setChief] = useState<ChiefReportEvent | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  // 数据采集过程（折叠思考过程展示）：{ key, status, message, request, response }
  const [collectSteps, setCollectSteps] = useState<
    { key: string; status: string; message: string; request?: Record<string, unknown> | null; response?: string | null }[]
  >([])
  const [collectOpen, setCollectOpen] = useState(false)
  // 角色 tab：当前选中的专家（展示该专家的全部轮次意见）
  const [activeExpertId, setActiveExpertId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => {
    setOpinions([])
    setChief(null)
    setStatusText('')
    setCurrentRound(0)
    setErrorMsg('')
    setCollectSteps([])
    setCollectOpen(false)
    setActiveExpertId(null)
  }, [])

  const run = useCallback(() => {
    if (!question.trim() || phase === 'running') return
    abortRef.current?.abort()
    reset()
    setPhase('running')
    onRunningChange?.(true)
    setStatusText('专家团已就位，等待首席召集…')

    const appendOrUpdate = (expertId: string, round: number, content: string, streaming: boolean, data?: ExpertOpinionData) => {
      setOpinions((prev) => {
        const idx = prev.findIndex((o) => o.expertId === expertId && o.round === round)
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = {
            ...next[idx],
            content: next[idx].content + content,
            streaming,
            // 结构化观点判断：首片 data 补齐后持久化
            stance: data?.stance ?? next[idx].stance,
            confidence: data?.confidence ?? next[idx].confidence,
            keyEvidence: data?.key_evidence ?? next[idx].keyEvidence,
            confidenceDelta: data?.confidence_delta ?? next[idx].confidenceDelta,
            revisedStance: data?.revised_stance ?? next[idx].revisedStance,
          }
          return next
        }
        return [{ expertId, round, content, streaming, ...(data ? {
          stance: data.stance,
          confidence: data.confidence,
          keyEvidence: data.key_evidence,
          confidenceDelta: data.confidence_delta,
          revisedStance: data.revised_stance,
        } : {}) }]
      })
    }

    const ctrl = startTeamAnalysis(
      {
        question: question.trim(),
        scenario: config.scenario,
        expert_ids: customMode ? config.expertIds : undefined,
        rounds: config.rounds,
        // 显式绑定的标的 → 传 ticker，使个股数据可采集
        ticker: config.ticker,
      },
      {
        onEvent: (e: TeamStreamEvent) => {
          switch (e.type) {
            case 'status':
              setStatusText(e.message)
              break
            case 'data_collect': {
              // 数据采集过程：追加到折叠思考过程列表（含协议请求/响应）
              const d = e.data
              if (d?.key) {
                const k = d.key
                setCollectSteps((prev) => [
                  ...prev.filter((s) => s.key !== k),
                  { key: k, status: d.status ?? 'running', message: d.message ?? '', request: d.request, response: d.response },
                ])
              }
              break
            }
            case 'expert_opinion':
              appendOrUpdate(e.expert_id, e.round, e.content, true, e.data)
              break
            case 'round_complete':
              setCurrentRound(e.round)
              // 该轮所有专家落定（停止流式光标）
              setOpinions((prev) => prev.map((o) => (o.round === e.round ? { ...o, streaming: false } : o)))
              if (e.message) setStatusText(e.message)
              break
            case 'chief_report':
              setChief(e)
              setStatusText('首席投资官正在收敛最终研判…')
              break
            case 'done':
              setPhase('done')
              onRunningChange?.(false)
              setStatusText('投决会结束')
              break
            case 'error':
              setErrorMsg(e.message)
              setPhase('error')
              onRunningChange?.(false)
              break
          }
        },
        onError: (err) => {
          setErrorMsg(err.message || '网络异常，分析中断')
          setPhase('error')
          onRunningChange?.(false)
        },
      },
    )
    abortRef.current = ctrl
  }, [question, config, customMode, phase, reset, onRunningChange])

  // runToken 变化时自动发起
  useEffect(() => {
    if (runToken > 0) run()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runToken])

  const stop = () => {
    abortRef.current?.abort()
    setPhase((p) => (p === 'running' ? 'done' : p))
    onRunningChange?.(false)
    setStatusText('已中止')
  }

  // 角色 tab：从已到意见里按 expertId 去重得到专家列表
  const expertList = Array.from(new Set(opinions.map((o) => o.expertId)))
  // 首个专家意见到达时自动选中该角色
  useEffect(() => {
    if (!activeExpertId && expertList.length > 0) {
      setActiveExpertId(expertList[0])
    }
  }, [expertList, activeExpertId])
  const activeExpert = activeExpertId ?? expertList[0] ?? null
  const activeExpertOpinions = activeExpert ? opinions.filter((o) => o.expertId === activeExpert) : []

  return (
    <div className="flex h-full flex-col">
      {/* 进度条 / 状态 */}
      <div className="flex items-center gap-2 border-b border-border/40 px-3 py-2">
        {phase === 'running' ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-scene" />
        ) : phase === 'error' ? (
          <AlertTriangle className="h-3.5 w-3.5 text-red-400" />
        ) : (
          <Crown className="h-3.5 w-3.5 text-yellow-300" />
        )}
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">{statusText}</span>
        {phase === 'running' && (
          <button
            type="button"
            onClick={stop}
            className="flex items-center gap-1 rounded-md border border-red-400/30 px-1.5 py-0.5 text-[10px] text-red-400 hover:bg-red-500/10"
          >
            <Square className="h-2.5 w-2.5" /> 中止
          </button>
        )}
      </div>

      {/* 滚动内容区 */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {phase === 'idle' && (
          <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground">
            <Crown className="mb-2 h-8 w-8 opacity-40" />
            <p className="text-xs">配置左侧阵容与命题，点击「发起投研会」</p>
            <p className="mt-1 text-[10px] opacity-70">17 位专家 · 6 大团队 · 多轮辩论 · 首席收敛</p>
          </div>
        )}

        {errorMsg && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-2 text-[11px] text-red-300">
            {errorMsg}
          </div>
        )}

        {/* 数据采集过程：折叠思考过程（复用 Research 折叠形态） */}
        {collectSteps.length > 0 && (
          <details
            open={collectOpen}
            onToggle={(e) => setCollectOpen((e.target as HTMLDetailsElement).open)}
            className="group rounded-xl border border-border/40 bg-white/[0.03]"
          >
            <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-[11px] font-medium text-muted-foreground hover:text-foreground select-none">
              <Database className="h-3.5 w-3.5 text-scene" />
              <span>数据采集过程</span>
              <span className="ml-auto text-[10px] text-muted-foreground/70">
                {collectSteps.length} 项 · {collectSteps.filter((s) => s.status === 'success').length} 完成
              </span>
              <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
            </summary>
            <div className="max-h-56 overflow-y-auto border-t border-border/30 px-3 py-2">
              {collectSteps.map((s) => {
                const isErr = s.status === 'error' || s.status === 'timeout' || s.status === 'skipped'
                return (
                  <div key={s.key} className="flex items-start gap-2 py-1 text-[11px]">
                    <span className={cn(
                      'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                      isErr ? 'bg-red-400' : s.status === 'success' ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse',
                    )} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-foreground/80">{s.key}</span>
                        <span className={cn(
                          'text-[10px] px-1 rounded',
                          isErr ? 'text-red-300' : s.status === 'success' ? 'text-emerald-300' : 'text-amber-300',
                        )}>
                          {s.status}
                        </span>
                      </div>
                      {s.message && <div className="truncate text-[10px] text-muted-foreground/70">{s.message}</div>}
                      {(s.request || s.response) && (
                        <details className="group ml-1 mt-0.5 rounded border border-border/30 bg-secondary/10 px-1.5 py-0.5">
                          <summary className="cursor-pointer select-none text-[10px] text-muted-foreground hover:text-foreground">
                            协议 请求/响应
                          </summary>
                          <div className="space-y-1 pt-1 text-[10px] leading-relaxed">
                            {s.request && (
                              <div className="text-foreground/70">
                                <span className="text-muted-foreground/70">请求 </span>
                                <code className="break-all font-mono">{JSON.stringify(s.request)}</code>
                              </div>
                            )}
                            {s.response && (
                              <div className="text-foreground/70">
                                <span className="text-muted-foreground/70">响应 </span>
                                <code className="break-all whitespace-pre-wrap font-mono">{s.response}</code>
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </details>
        )}

        {/* 研究员研判：角色 tab，逐专家展示意见 */}
        {opinions.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
              研究员研判 {currentRound > 0 && `· 第 ${currentRound} 轮`}
            </div>
            {/* 角色 tab 栏 */}
            <div className="flex gap-1 overflow-x-auto pb-1">
              {expertList.map((eid) => {
                const p = expertById(eid)
                const isActive = eid === activeExpert
                const rounds = opinions.filter((o) => o.expertId === eid)
                return (
                  <button
                    key={eid}
                    type="button"
                    onClick={() => setActiveExpertId(eid)}
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
            </div>
            {/* 当前选中角色的意见（含其全部轮次） */}
            {activeExpertOpinions.map((o, i) => (
              <ExpertOpinionCard key={`${o.expertId}-${o.round}-${i}`} opinion={o} campBorder />
            ))}
          </div>
        )}

        {/* 首席最终报告 */}
        {chief && (
          <div className="rounded-xl border border-yellow-300/40 bg-yellow-300/5 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Crown className="h-4 w-4 text-yellow-300" />
              <span className="text-xs font-bold text-yellow-300">首席投资官 · 最终研判</span>
              {typeof chief.bullish_probability === 'number' && (
                <span className="ml-auto rounded-full border border-scene/40 bg-scene/10 px-2 py-0.5 text-[10px] text-scene">
                  看涨概率 {chief.bullish_probability}%
                </span>
              )}
            </div>
            <BriefingMarkdown content={chief.content} />
          </div>
        )}
      </div>
    </div>
  )
}
