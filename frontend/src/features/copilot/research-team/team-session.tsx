/**
 * RESEARCH-TEAM-05: 投研团队会话视图
 * 接收配置 → 发起 SSE → 流式渲染专家 Round1/Round2 卡片 → 首席最终报告。
 */
'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Crown, AlertTriangle, Square, Database, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ChiefReportPanel } from './chief-report-panel'
import { ExpertOpinionCard, type ExpertOpinionState } from './expert-opinion-card'
import { expertById } from './expert-roster'
import {
  startTeamAnalysis,
  fetchSession,
  type TeamStreamEvent,
  type ChiefReportEvent,
  type ExpertOpinionData,
  type HistoricalOpinion,
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
  // 出战阵容：从首个 status 事件的 data.experts 中预提取，用于在观点到达前展示等待占位
  const [lineupExpertIds, setLineupExpertIds] = useState<string[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // 用户主动划走滚动后，停止自动聚焦到流式中的分析师面板
  const userScrolledRef = useRef(false)

  const reset = useCallback(() => {
    setOpinions([])
    setChief(null)
    setStatusText('')
    setCurrentRound(0)
    setErrorMsg('')
    setCollectSteps([])
    setCollectOpen(false)
    setLineupExpertIds([])
    userScrolledRef.current = false
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

    // 完成帧后的补全对账：拿持久化会话补齐流式丢帧导致的缺失/空白观点，
    // 保证无论传输层丢了多少帧，结束后所有专家 × 所有轮次内容都完整展示（与历史详情一致）
    const reconcileFromSession = async (sid: string) => {
      try {
        const detail = await fetchSession(sid)
        if (!detail) return
        const fromAllRounds = Object.values(detail.all_rounds ?? {}).flat()
        const persisted: HistoricalOpinion[] = fromAllRounds.length > 0
          ? fromAllRounds
          : [...(detail.round1_opinions ?? []), ...(detail.round2_opinions ?? [])]
        if (persisted.length > 0) {
          setOpinions((prev) => {
            const next = [...prev]
            for (const p of persisted) {
              const filled: ExpertOpinionState = {
                expertId: p.expert_id,
                round: p.round,
                content: p.reasoning || p.stance || '',
                streaming: false,
                stance: p.stance,
                confidence: p.confidence,
                keyEvidence: p.key_evidence,
                confidenceDelta: p.confidence_delta,
                revisedStance: p.revised_stance,
              }
              const idx = next.findIndex((o) => o.expertId === p.expert_id && o.round === p.round)
              if (idx < 0) next.push(filled)
              else if (!next[idx].content.trim()) next[idx] = { ...next[idx], ...filled }
            }
            return next
          })
        }
        // 首席正文缺失时用持久化 full_report 兜底（已有流式正文则不动）
        const rep = detail.chief_report
        if (rep?.full_report) {
          setChief((prev) => (prev && !prev.content.trim() ? { ...prev, content: rep.full_report as string } : prev))
        }
      } catch {
        /* 对账失败不阻断：流式内容保持原样 */
      }
    }

    const ctrl = startTeamAnalysis(
      {
        question: question.trim(),
        scenario: config.scenario,
        expert_ids: customMode ? config.expertIds : undefined,
        rounds: config.rounds,
        // 显式绑定的标的 → 传 ticker，使个股数据可采集
        ticker: config.ticker,
        // 声明式分析标的（命题携带），与 ticker 合并供后端解析/LLM 推导
        symbols: config.symbols,
      },
      {
        onEvent: (e: TeamStreamEvent) => {
          switch (e.type) {
            case 'status':
              setStatusText(e.message)
              // 首个 status 事件携带出战阵容 → 预建 tab
              if (e.data?.experts?.length) {
                const ids = e.data.experts.map((ex) => ex.id)
                setLineupExpertIds(ids)
              }
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
            case 'expert_opinion': {
              // 身份字段: 顶层优先(新协议每片携带), 缺失时回退首片 data(兼容旧后端);
              // 无身份的帧丢弃, 避免观点落入匿名 tab
              const eid = e.expert_id ?? e.data?.expert_id
              if (eid) appendOrUpdate(eid, e.round ?? e.data?.round ?? 1, e.content, true, e.data)
              break
            }
            case 'round_complete':
              setCurrentRound(e.round ?? 0)
              // 该轮所有专家落定（停止流式光标）
              setOpinions((prev) => prev.map((o) => (o.round === e.round ? { ...o, streaming: false } : o)))
              if (e.message) setStatusText(e.message)
              break
            case 'chief_report':
              setStatusText('首席投资官正在收敛最终研判…')
              // 真流式协议：增量片不带 data，末帧（完成帧）才携带结构化字段；
              // prev.data 为空对象时不得阻断后续完成帧 data（{} 非 nullish，?? 会原样钉死）
              setChief((prev) =>
                prev
                  ? {
                      ...prev,
                      content: prev.content + (e.content ?? ''),
                      data: prev.data && Object.keys(prev.data).length
                        ? prev.data
                        : e.data && Object.keys(e.data).length
                          ? e.data
                          : undefined,
                    }
                  : e,
              )
              break
            case 'done': {
              setPhase('done')
              onRunningChange?.(false)
              setStatusText('投决会结束')
              // 拿持久化会话对账补全，确保内容与历史详情一致完整
              const sid = e.data?.session_id ?? e.session_id
              if (sid) void reconcileFromSession(sid)
              break
            }
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

  // 全量时间线：所有专家 × 所有轮次内容同屏持久展示（无 tab 切换，流式完成后内容不消失）
  const expertList = Array.from(new Set([...lineupExpertIds, ...opinions.map((o) => o.expertId)]))
  const hasAnyContent = expertList.length > 0 || !!chief
  // 轮次严格顺序推进：已见最大轮次；运行中再补上正在进行的下一轮（含等待占位）
  const maxRoundSeen = opinions.reduce((m, o) => Math.max(m, o.round), 0)
  const activeRound = phase === 'running' ? currentRound + 1 : 0
  const roundsToShow = Math.max(maxRoundSeen, activeRound)

  // 自动聚焦：流式进行中，自动滚动到正在输出的分析师面板；用户主动划走后不再强制定位
  const streamingOp = opinions.find((o) => o.streaming)
  useEffect(() => {
    if (userScrolledRef.current) return
    if (!streamingOp) return
    const el = document.getElementById(`opinion-${streamingOp.expertId}-${streamingOp.round}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [streamingOp?.expertId, streamingOp?.round])

  // 定位到指定分析师（轴上标识点击）：主动定位后恢复自动聚焦能力
  const focusExpert = (expertId: string) => {
    userScrolledRef.current = false
    const latest = opinions
      .filter((o) => o.expertId === expertId)
      .sort((a, b) => b.round - a.round)[0]
    const targetId = latest
      ? `opinion-${latest.expertId}-${latest.round}`
      : `opinion-pending-${expertId}`
    const el = document.getElementById(targetId)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

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

      {/* 主体：左侧时间线轴 + 右侧滚动内容区 */}
      <div className="flex min-h-0 flex-1">
        {/* 时间线轴：可点击的分析师标识，高亮当前输出者 */}
        {expertList.length > 0 && (
          <div className="flex w-11 shrink-0 flex-col items-center gap-1.5 border-r border-border/30 py-3">
            <span className="mb-1 text-[9px] uppercase tracking-wide text-muted-foreground/60">分析师</span>
            {expertList.map((eid) => {
              const ops = opinions.filter((o) => o.expertId === eid)
              const latest = ops.sort((a, b) => b.round - a.round)[0]
              const isStreaming = ops.some((o) => o.streaming)
              const isDone = !!latest?.content.trim()
              const p = expertById(eid)
              return (
                <button
                  key={eid}
                  type="button"
                  title={p?.name ?? eid}
                  onClick={() => focusExpert(eid)}
                  className={cn(
                    'relative flex h-8 w-8 items-center justify-center rounded-full border text-[13px] transition-colors',
                    isStreaming
                      ? 'border-scene/70 bg-scene/15 text-foreground ring-2 ring-scene/40'
                      : isDone
                        ? 'border-emerald-400/40 bg-emerald-400/10 text-foreground'
                        : 'border-white/15 bg-white/[0.03] text-muted-foreground hover:border-white/30',
                  )}
                >
                  <span>{p?.glyph ?? '🧑'}</span>
                  {isStreaming && (
                    <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-ping rounded-full bg-scene" />
                  )}
                </button>
              )
            })}
            {/* 首席投资官（时间线末尾锚点） */}
            {(chief || phase === 'running') && (
              <button
                type="button"
                title="首席投资官 · 最终研判"
                onClick={() => {
                  userScrolledRef.current = false
                  document.getElementById('opinion-chief')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
                className={cn(
                  'relative flex h-8 w-8 items-center justify-center rounded-full border text-[13px] transition-colors',
                  chief?.content
                    ? 'border-yellow-300/50 bg-yellow-300/10 text-yellow-200'
                    : 'border-yellow-300/30 bg-yellow-300/5 text-yellow-300/70 hover:border-yellow-300/60',
                )}
              >
                <Crown className="h-4 w-4" />
                {phase === 'running' && !chief && (
                  <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-ping rounded-full bg-yellow-300" />
                )}
              </button>
            )}
          </div>
        )}

        {/* 滚动内容区：用户主动 wheel/touch 划走后停止自动聚焦 */}
        <div
          ref={scrollRef}
          onWheel={() => { userScrolledRef.current = true }}
          onTouchMove={() => { userScrolledRef.current = true }}
          className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3"
        >
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

        {/* 研究员研判：扁平时间线 —— 每位分析师一张独立面板，按生成顺序(轮次→阵容)排列，
            内容在面板内流式展示并持久保留；不再使用「第 X 轮 · 独立研判」聚合面板 */}
        {hasAnyContent && (
          <div className="space-y-2">
            {opinions
              .slice()
              .sort((a, b) => {
                if (a.round !== b.round) return a.round - b.round
                return expertList.indexOf(a.expertId) - expertList.indexOf(b.expertId)
              })
              .map((o, i) => (
                <div key={`${o.expertId}-${o.round}-${i}`} id={`opinion-${o.expertId}-${o.round}`}>
                  <ExpertOpinionCard opinion={o} campBorder />
                </div>
              ))}
            {/* 当前运行轮次：尚未产出观点的分析师占位（每张独立面板，避免聚合感） */}
            {phase === 'running' && Array.from({ length: roundsToShow }, (_, i) => i + 1).map((r) => {
              const servedIds = new Set(opinions.filter((o) => o.round === r).map((o) => o.expertId))
              const pending = expertList.filter((eid) => !servedIds.has(eid))
              const isLiveRound = r === activeRound
              return pending.map((eid) => {
                const p = expertById(eid)
                return (
                  <div
                    key={`pending-${eid}-${r}`}
                    id={`opinion-pending-${eid}`}
                    className="flex items-center gap-2 rounded-xl border border-border/30 bg-white/[0.02] px-3 py-2 text-[11px] text-muted-foreground"
                  >
                    {isLiveRound ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-scene" />
                    ) : (
                      <span className="text-xs">{p?.glyph ?? '🧑'}</span>
                    )}
                    <span>{p?.name ?? eid}</span>
                    <span className="text-muted-foreground/60">
                      {isLiveRound ? `第 ${r} 轮研判中，观点将流式展示…` : `第 ${r} 轮未产出观点`}
                    </span>
                  </div>
                )
              })
            })}
            {/* 首席投资官收敛报告：结构化字段由完成帧补全，流式正文持久保留 */}
            {chief ? (
              <div id="opinion-chief">
                <ChiefReportPanel report={{
                probability: chief.bullish_probability ?? chief.data?.probability_assessment,
                body: chief.content,
                finalRecommendation: chief.data?.final_recommendation,
                consensusAreas: chief.data?.consensus_areas,
                divergenceAreas: chief.data?.divergence_areas,
                strongestBullCase: chief.data?.strongest_bull_case,
                strongestBearCase: chief.data?.strongest_bear_case,
                riskWarnings: chief.data?.risk_warnings,
                minorityOpinion: chief.data?.minority_opinion,
              }} />
              </div>
            ) : phase === 'running' && currentRound >= (config.rounds || 2) ? (
              <div className="flex items-center gap-2 rounded-xl border border-yellow-300/20 bg-yellow-300/5 p-4 text-xs text-yellow-300/60">
                <Loader2 className="h-4 w-4 animate-spin" />
                首席投资官正在收敛最终研判…
              </div>
            ) : null}
          </div>
        )}


      </div>
      </div>
    </div>
  )
}
