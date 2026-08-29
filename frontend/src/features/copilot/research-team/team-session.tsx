/**
 * RESEARCH-TEAM-05: 投研团队会话视图
 * 接收配置 → 发起 SSE → 流式渲染专家 Round1/Round2 卡片 → 首席最终报告。
 */
'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Crown, AlertTriangle, Square, Database, ChevronRight, RotateCcw } from 'lucide-react'
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
  const [collectOpen, setCollectOpen] = useState(true)
  // 出战阵容：从首个 status 事件的 data.experts 中预提取，用于在观点到达前展示等待占位
  const [lineupExpertIds, setLineupExpertIds] = useState<string[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // 用户主动划走滚动后，停止自动聚焦到流式中的分析师面板；
  // 用户通过滚轮/拖拽/触控板离开阅读区即视为"主动查看"，不再强行拉回顶部
  const userScrolledRef = useRef(false)
  // 滚动区是否贴近底部（贴近底部时轻微的自动跟随不会造成视觉跳动）
  const nearBottomRef = useRef(false)

  // 流式节流：SSE 可能一次性把整段文本推过来，直接写入 state 会"瞬间刷完"看不清。
  // 这里把增量文本先放进 ref 缓冲，再由固定节拍的定时器逐字/逐块吐出，形成平滑打字机效果。
  const buffersRef = useRef<Record<string, string>>({})
  const flushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 每个节拍吐出的字符数：越小越慢。配合下方 28ms 节拍 ≈ 每秒 ~140 字
  const FLUSH_CHARS_PER_TICK = 4
  const FLUSH_INTERVAL_MS = 28

  const reset = useCallback(() => {
    setOpinions([])
    setChief(null)
    setStatusText('')
    setCurrentRound(0)
    setErrorMsg('')
    setCollectSteps([])
    setCollectOpen(true)
    setLineupExpertIds([])
    buffersRef.current = {}
    if (flushTimerRef.current) {
      clearInterval(flushTimerRef.current)
      flushTimerRef.current = null
    }
    userScrolledRef.current = false
  }, [])

  const run = useCallback(() => {
    if (!question.trim() || phase === 'running') return
    abortRef.current?.abort()
    reset()
    setPhase('running')
    onRunningChange?.(true)
    setStatusText('专家团已就位，等待首席召集…')

    // 流式节流：把增量文本写入 ref 缓冲，由 flushTimer 按固定节拍吐出到 state，
    // 避免后端一次性推送整段导致"瞬间刷完"。结构化字段(data)仍即时落库。
    const key = (expertId: string, round: number) => `${expertId}#${round}`
    // 立即停掉节流定时器，并把缓冲里残留文本一次性吐出，保证 done/error 时内容不丢
    const flushAllNow = () => {
      if (flushTimerRef.current) {
        clearInterval(flushTimerRef.current)
        flushTimerRef.current = null
      }
      const buf = buffersRef.current
      const keys = Object.keys(buf)
      if (keys.length === 0) return
      setOpinions((prev) => {
        const next = [...prev]
        for (const k of keys) {
          const pending = buf[k]
          if (!pending) continue
          const [eid, r] = k.split('#')
          const round = Number(r)
          const idx = next.findIndex((o) => o.expertId === eid && o.round === round)
          if (idx >= 0) next[idx] = { ...next[idx], content: next[idx].content + pending }
        }
        return next
      })
      buffersRef.current = {}
    }
    const appendOrUpdate = (expertId: string, round: number, content: string, streaming: boolean, data?: ExpertOpinionData) => {
      // 1) 确保该专家本轮的占位卡片已存在（立即显示，不等流式内容）
      setOpinions((prev) => {
        const idx = prev.findIndex((o) => o.expertId === expertId && o.round === round)
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = {
            ...next[idx],
            streaming,
            stance: data?.stance ?? next[idx].stance,
            confidence: data?.confidence ?? next[idx].confidence,
            keyEvidence: data?.key_evidence ?? next[idx].keyEvidence,
            confidenceDelta: data?.confidence_delta ?? next[idx].confidenceDelta,
            revisedStance: data?.revised_stance ?? next[idx].revisedStance,
          }
          return next
        }
        return [{ expertId, round, content: '', streaming, ...(data ? {
          stance: data.stance,
          confidence: data.confidence,
          keyEvidence: data.key_evidence,
          confidenceDelta: data.confidence_delta,
          revisedStance: data.revised_stance,
        } : {}) }, ...prev]
      })
      // 2) 实时文本进入缓冲，由节流定时器逐步显示
      if (content) {
        buffersRef.current[key(expertId, round)] = (buffersRef.current[key(expertId, round)] ?? '') + content
        if (!flushTimerRef.current) {
          flushTimerRef.current = setInterval(() => {
            const buf = buffersRef.current
            const keys = Object.keys(buf)
            if (keys.length === 0) return
            setOpinions((prev) => {
              let changed = false
              const next = [...prev]
              for (const k of keys) {
                const pending = buf[k]
                if (!pending) continue
                const take = pending.slice(0, FLUSH_CHARS_PER_TICK)
                const rest = pending.slice(FLUSH_CHARS_PER_TICK)
                buf[k] = rest
                if (!take) continue
                changed = true
                const [eid, r] = k.split('#')
                const round = Number(r)
                const idx = next.findIndex((o) => o.expertId === eid && o.round === round)
                if (idx >= 0) next[idx] = { ...next[idx], content: next[idx].content + take }
              }
              return changed ? next : prev
            })
          }, FLUSH_INTERVAL_MS)
        }
      }
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
              if (eid) {
                // 完成帧识别：增量片不带 data，结构化 data 仅由末帧携带。
                // 收到即判定该专家本轮落定、立即收起流式光标——否则超时/异常的占位观点
                // （content 为空、仅带 stance）会一直卡在"撰写中…"，明明已是终态
                const isFinalFrame = !!e.data && Object.keys(e.data).length > 0
                appendOrUpdate(eid, e.round ?? e.data?.round ?? 1, e.content, !isFinalFrame, e.data)
              }
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
              flushAllNow()
              setPhase('done')
              onRunningChange?.(false)
              setStatusText('投决会结束')
              // 拿持久化会话对账补全，确保内容与历史详情一致完整
              const sid = e.data?.session_id ?? e.session_id
              if (sid) void reconcileFromSession(sid)
              break
            }
            case 'error':
              flushAllNow()
              setErrorMsg(e.message)
              setPhase('error')
              onRunningChange?.(false)
              break
          }
        },
        onError: (err) => {
          // 网络中断：把缓冲里已收到的残片吐出（部分内容总比空白好），再进入错误态
          flushAllNow()
          setErrorMsg(err.message || '网络异常，分析中断')
          setPhase('error')
          onRunningChange?.(false)
        },
        // NET-RETRY: 传输层瞬断自动重连（客户端指数退避）。重连 = 从头重跑，
        // 必须清空已收到的半程内容，否则重跑后同一专家卡片文本会叠加重复
        onRetry: (attemptNo, maxRetries) => {
          reset()
          setPhase('running')
          onRunningChange?.(true)
          setStatusText(`网络中断，正在自动重连（第 ${attemptNo}/${maxRetries} 次）…`)
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
  // 轮次严格顺序推进：已见最大轮次；运行中再补上正在进行的下一轮（含等待占位）
  const maxRoundSeen = opinions.reduce((m, o) => Math.max(m, o.round), 0)
  // 运行中：activeRound = 当前已完成轮 + 1（正在进行的轮）；且严格受 config.rounds 上限约束，避免越界轮次占位
  const totalRounds = config?.rounds ?? 2
  const activeRound = phase === 'running' ? Math.min(currentRound + 1, totalRounds) : 0
  const roundsToShow = Math.max(maxRoundSeen, activeRound)

  // 自动聚焦：流式进行中，自动滚动到正在输出的分析师面板；
  // 仅当用户未主动查看别处、且当前贴近底部（流式追加内容）时才轻微跟随，避免把正在阅读的人强行拉走
  const streamingOp = opinions.find((o) => o.streaming)
  useEffect(() => {
    if (userScrolledRef.current) return
    if (!streamingOp) return
    // 不在底部时（用户正在看历史内容）不强行拉顶，避免画面跳动
    if (!nearBottomRef.current) return
    const el = document.getElementById(`opinion-${streamingOp.expertId}-${streamingOp.round}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'end' })
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
    <div className="flex h-full min-h-0 flex-col">
      {/* 进度条 / 状态 */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-3 py-2">
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

        {/* 滚动内容区：用户主动 wheel/拖拽/触控板 划走后停止自动聚焦；
            贴近底部时恢复轻微跟随（新内容自然滚入） */}
        <div
          ref={scrollRef}
          onWheel={() => { userScrolledRef.current = true }}
          onTouchMove={() => { userScrolledRef.current = true }}
          onPointerDown={() => { userScrolledRef.current = true }}
          onScroll={(e) => {
            const el = e.currentTarget
            const distance = el.scrollHeight - el.scrollTop - el.clientHeight
            nearBottomRef.current = distance < 80
            // 用户主动把内容滚回底部（距离 < 80px）视为恢复跟随
            if (distance < 80) userScrolledRef.current = false
          }}
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
            <div className="flex items-start gap-2">
              <span className="min-w-0 flex-1 break-words">{errorMsg}</span>
              {/* NET-RETRY: 自动重连耗尽后的手动兜底——重新发起整场投研会 */}
              <button
                type="button"
                onClick={run}
                className="flex shrink-0 items-center gap-1 rounded-md border border-red-400/40 px-2 py-0.5 text-[10px] text-red-200 transition-colors hover:bg-red-500/20"
              >
                <RotateCcw className="h-2.5 w-2.5" /> 重新发起
              </button>
            </div>
          </div>
        )}

        {/* 数据采集过程：折叠思考过程（复用 Research 折叠形态） */}
        {collectSteps.length > 0 && (
          <details
            open={collectOpen || phase === 'running'}
            onToggle={(e) => setCollectOpen((e.target as HTMLDetailsElement).open)}
            className="group rounded-xl border border-border/40 bg-white/[0.03]"
          >
            <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-[11px] font-medium text-muted-foreground hover:text-foreground select-none">
              <Database className="h-3.5 w-3.5 text-scene" />
              <span>数据采集过程</span>
              <span className="ml-auto text-[10px] text-muted-foreground/70">
                {collectSteps.length} 项 · {collectSteps.filter((s) => s.status === 'success').length} 完成
                {phase === 'running' && collectSteps.some((s) => s.status !== 'success') && ' · 采集中'}
              </span>
              <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
            </summary>
            <div className="max-h-56 overflow-y-auto border-t border-border/30 px-3 py-2">
              {collectSteps.map((s) => {
                const isErr = s.status === 'error' || s.status === 'timeout' || s.status === 'skipped'
                // 友好文案：将后端透传的"网关 400/熔断/限流"归纳为可行动提示，避免直接甩原始报错
                const rawMsg = s.message || ''
                const isTransient = /熔断|限流|circuit|rate.?limit|cooldown|暂不可用|网关报错|400|503/i.test(rawMsg)
                const friendlyMsg = isTransient
                  ? '数据源临时不可用（熔断/限流冷却中），稍后重试即可恢复'
                  : rawMsg
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
                          isErr ? (isTransient ? 'text-amber-300' : 'text-red-300')
                            : s.status === 'success' ? 'text-emerald-300' : 'text-amber-300',
                        )}>
                          {isTransient && isErr ? 'retry' : s.status}
                        </span>
                      </div>
                      {friendlyMsg && <div className="truncate text-[10px] text-muted-foreground/70" title={rawMsg}>{friendlyMsg}</div>}
                      {(s.request || s.response) && (
                        <details className="group ml-1 mt-0.5 rounded border border-border/30 bg-secondary/10 px-1.5 py-0.5">
                          <summary className="cursor-pointer select-none text-[10px] text-muted-foreground hover:text-foreground">
                            协议 请求/响应
                          </summary>
                          <div className="max-h-72 space-y-1 overflow-y-auto pt-1 text-[10px] leading-relaxed">
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

        {/* 研究员研判：扁平时间线 —— 出场阵容里每位分析师在每一可见轮次都固定占一张面板，
            尚未发言的显示为占位(等待发言…)，已发言的持久保留流式内容。
            这样「全过程所有分析师」始终同屏可见，而非只显示正在流式的那一位。 */}
        {expertList.length > 0 && (
          <div className="space-y-2">
            {Array.from({ length: roundsToShow }, (_, ri) => ri + 1).flatMap((r) =>
              expertList.map((eid, i) => {
                const existing = opinions.find((o) => o.expertId === eid && o.round === r)
                const opinion: ExpertOpinionState = existing ?? {
                  expertId: eid,
                  round: r,
                  content: '',
                  streaming: phase === 'running' && r === activeRound,
                }
                return (
                  <div key={`${eid}-${r}-${i}`} id={`opinion-${eid}-${r}`}>
                    <ExpertOpinionCard opinion={opinion} campBorder />
                  </div>
                )
              }),
            )}
            {/* 当前运行轮次：仅渲染一个「等待下一位专家发言」气泡，标记本轮还在进行中 */}
            {phase === 'running' && (
              <div
                key={`pending-round-${activeRound}`}
                className="flex items-center gap-2 rounded-xl border border-border/30 bg-white/[0.02] px-3 py-2 text-[11px] text-muted-foreground"
              >
                <Loader2 className="h-3.5 w-3.5 animate-spin text-scene" />
                <span>第 {activeRound} 轮进行中，等待下一位专家发言…</span>
              </div>
            )}
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
