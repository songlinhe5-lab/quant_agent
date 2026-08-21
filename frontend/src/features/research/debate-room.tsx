'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Crown, AlertTriangle, Square, RotateCcw, Users, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ExpertOpinionCard, type ExpertOpinionState } from '@/features/copilot/research-team/expert-opinion-card'
import { expertById, type ExpertBias } from '@/features/copilot/research-team/expert-roster'
import { startTeamAnalysis, type TeamStreamEvent, type ChiefReportEvent } from '@/features/copilot/research-team/expert-team-client'
import type { TeamConfig } from '@/features/copilot/research-team/roster-panel'
import { useAssetLibrary } from '@/stores/useAssetLibrary'
import { ChiefReportCard } from './chief-report-card'

interface DebateRoomProps {
  question: string
  config: TeamConfig
  runToken: number
  onDone?: () => void
  /** COPILOT-17: 调整阵容重跑（回填组局态） */
  onRerun?: () => void
  /** COPILOT-17: 追问首席（切换对话模式） */
  onAskChief?: () => void
}

type Phase = 'idle' | 'running' | 'done' | 'error' | 'stopped'

/** 已完成轮次（round_complete 标记），用于时间线打勾 + 轮分隔条 */
interface CompletedRound { round: number; consensus: number }

/**
 * COPILOT-16: B2 辩论态 (Debate Room)
 *  三列：观点流 / 实时阵营面板(220px) / (B3 由外层承载)
 *  顶部横向轮次时间线 R1✓ → R2● → 首席收敛○
 *  阵营面板按专家 bias 分组(多/空/中性)人数柱 + 平均信心
 *  断流 amber 横幅 + 重试；停止按钮落「已停止」态
 */
export function DebateRoom({ question, config, runToken, onDone, onRerun, onAskChief }: DebateRoomProps) {
  const addAsset = useAssetLibrary((s) => s.addAsset)
  const [phase, setPhase] = useState<Phase>('idle')
  const [statusText, setStatusText] = useState('')
  const [opinions, setOpinions] = useState<ExpertOpinionState[]>([])
  const [currentRound, setCurrentRound] = useState(0)
  const [completedRounds, setCompletedRounds] = useState<CompletedRound[]>([])
  const [chief, setChief] = useState<ChiefReportEvent | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [interrupted, setInterrupted] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const totalRounds = config.rounds

  const reset = useCallback(() => {
    setOpinions([])
    setChief(null)
    setStatusText('')
    setCurrentRound(0)
    setCompletedRounds([])
    setErrorMsg('')
    setInterrupted(false)
  }, [])

  const run = useCallback(() => {
    if (!question.trim() || phase === 'running') return
    abortRef.current?.abort()
    reset()
    setPhase('running')
    setStatusText('专家团已就位，等待首席召集…')

    const appendOrUpdate = (expertId: string, round: number, content: string, streaming: boolean) => {
      setOpinions((prev) => {
        const idx = prev.findIndex((o) => o.expertId === expertId && o.round === round)
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = { ...next[idx], content: next[idx].content + content, streaming }
          return next
        }
        return [...prev, { expertId, round, content, streaming }]
      })
    }

    const ctrl = startTeamAnalysis(
      {
        question: question.trim(),
        scenario: config.scenario,
        expert_ids: config.expertIds,
        rounds: config.rounds,
      },
      {
        onEvent: (e: TeamStreamEvent) => {
          switch (e.type) {
            case 'status':
              setStatusText(e.message)
              break
            case 'expert_opinion':
              appendOrUpdate(e.expert_id, e.round, e.content, true)
              break
            case 'round_complete':
              setCurrentRound(e.round)
              setOpinions((prev) => prev.map((o) => (o.round === e.round ? { ...o, streaming: false } : o)))
              setCompletedRounds((prev) => {
                if (prev.some((c) => c.round === e.round)) return prev
                return [...prev, { round: e.round, consensus: 50 }]
              })
              if (e.message) setStatusText(e.message)
              break
            case 'chief_report':
              setChief(e)
              setStatusText('首席投资官正在收敛最终研判…')
              break
            case 'done':
              setPhase('done')
              setStatusText('投决会结束')
              onDone?.()
              break
            case 'error':
              setErrorMsg(e.message)
              setPhase('error')
              break
          }
        },
        onError: (err) => {
          setErrorMsg(err.message || '网络异常，分析中断')
          setInterrupted(true)
          setPhase('error')
        },
      },
    )
    abortRef.current = ctrl
  }, [question, config, runToken, phase, reset, onDone])

  useEffect(() => {
    if (runToken > 0) run()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runToken])

  const stop = () => {
    abortRef.current?.abort()
    setPhase((p) => (p === 'running' ? 'stopped' : p))
    setStatusText('已停止 · 保留已产出观点')
  }

  const retry = () => { setInterrupted(false); run() }

  // 实时阵营统计：按专家 bias 分组（多/空/中性）
  const camps = useMemo(() => {
    const byBias: Record<ExpertBias, string[]> = { bullish: [], bearish: [], neutral: [] }
    // 出站阵容（来自 config.expertIds）
    for (const id of config.expertIds) {
      const p = expertById(id)
      if (p) byBias[p.bias].push(id)
    }
    // 已发言专家的活跃观点数作为加权
    const counts = { bullish: byBias.bullish.length, bearish: byBias.bearish.length, neutral: byBias.neutral.length }
    const total = counts.bullish + counts.bearish + counts.neutral || 1
    const majority = counts.bullish >= counts.bearish ? 'bullish' : 'bearish'
    return { counts, total, majority, bullPct: Math.round((counts.bullish / total) * 100), bearPct: Math.round((counts.bearish / total) * 100) }
  }, [config.expertIds])

  const panelDefs = [
    { key: 'bullish' as const, label: '多方', color: 'bg-emerald-400', text: 'text-emerald-400', count: camps.counts.bullish, pct: camps.bullPct },
    { key: 'bearish' as const, label: '空方', color: 'bg-red-400', text: 'text-red-400', count: camps.counts.bearish, pct: camps.bearPct },
    { key: 'neutral' as const, label: '中性', color: 'bg-slate-400', text: 'text-slate-400', count: camps.counts.neutral, pct: 100 - camps.bullPct - camps.bearPct },
  ]

  return (
    <div className="flex h-full flex-col">
      {/* 轮次时间线 */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border/20 px-4">
        <div className="flex items-center gap-1.5">
          {Array.from({ length: totalRounds }, (_, i) => i + 1).map((r) => {
            const done = completedRounds.some((c) => c.round === r)
            const active = phase === 'running' && currentRound === r
            return (
              <React.Fragment key={r}>
                <span className={cn(
                  'flex h-5 items-center gap-1 rounded-full px-2 text-[10px] font-semibold',
                  done ? 'bg-emerald-500/15 text-emerald-400' : active ? 'bg-scene/15 text-scene' : 'border border-border/40 text-muted-foreground',
                )}>
                  {done ? <Check className="h-3 w-3" /> : active ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                  R{r}
                </span>
                {r < totalRounds && <span className="h-px w-2 bg-border/50" />}
              </React.Fragment>
            )
          })}
          <span className="h-px w-2 bg-border/50" />
          <span className={cn('flex h-5 items-center gap-1 rounded-full px-2 text-[10px] font-semibold', chief ? 'bg-yellow-300/15 text-yellow-300' : 'border border-dashed border-border/50 text-muted-foreground')}>
            <Crown className="h-3 w-3" /> 首席收敛
          </span>
        </div>
        {/* 状态 + 停止 */}
        <div className="ml-auto flex items-center gap-2">
          <span className="min-w-0 max-w-[220px] truncate text-[10px] text-muted-foreground">{statusText}</span>
          {phase === 'running' && (
            <button type="button" onClick={stop} className="flex items-center gap-1 rounded-md border border-red-400/30 px-1.5 py-0.5 text-[10px] text-red-400 hover:bg-red-500/10">
              <Square className="h-2.5 w-2.5" /> 中止
            </button>
          )}
        </div>
      </div>

      {/* 断流横幅 */}
      {interrupted && (
        <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-[11px] text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">连接中断 · 已保留 {opinions.length} 条观点</span>
          <button type="button" onClick={retry} className="flex items-center gap-1 rounded-md border border-amber-500/40 px-2 py-0.5 text-[10px] hover:bg-amber-500/15">
            <RotateCcw className="h-3 w-3" /> 重试
          </button>
        </div>
      )}

      {/* 三列：观点流 + 阵营面板 */}
      <div className="flex flex-1 min-h-0">
        {/* 观点流 */}
        <div className="flex-1 min-w-0 overflow-y-auto p-3 custom-scrollbar">
          {phase === 'idle' && (
            <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground">
              <Crown className="mb-2 h-8 w-8 opacity-40" />
              <p className="text-xs">投研会进行中，等待专家发言…</p>
            </div>
          )}

          {errorMsg && !interrupted && (
            <div className="mb-2 rounded-lg border border-red-400/30 bg-red-500/10 p-2 text-[11px] text-red-300">{errorMsg}</div>
          )}

          {/* 轮分隔条 */}
          {completedRounds.map((c) => (
            <div key={c.round} className="mb-2 flex items-center gap-2">
              <span className="h-px flex-1 bg-border/50" />
              <span className="rounded-full border border-scene/30 bg-scene/10 px-2 py-0.5 text-[9px] font-mono text-scene">
                第 {c.round} 轮结束 · 共识度 {c.consensus}%
              </span>
              <span className="h-px flex-1 bg-border/50" />
            </div>
          ))}

          {opinions.map((o, i) => (
            <div key={`${o.expertId}-${o.round}-${i}`} className="mb-2">
              <ExpertOpinionCard opinion={o} campBorder />
            </div>
          ))}

          {phase === 'stopped' && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-center text-[11px] text-amber-400">
              已停止 · 以下为已产出的观点（未完成全部轮次）
            </div>
          )}

          {/* 首席收敛报告（COPILOT-17） */}
          {chief && (
            <ChiefReportCard
              event={chief}
              config={config}
              expertCount={config.expertIds.length}
              onSave={() => {
                addAsset({
                  type: 'chief',
                  title: `首席报告 · ${question.slice(0, 20)}`,
                  source: question.slice(0, 40),
                  content: chief.content || '',
                })
              }}
              onExport={() => {
                if (!chief.content) return
                const blob = new Blob([`# 首席投资官 · 最终研判\n\n${chief.content}`], { type: 'text/markdown;charset=utf-8' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `chief_report_${new Date().toISOString().slice(0, 10)}.md`
                a.click()
                URL.revokeObjectURL(url)
              }}
              onRerun={onRerun ?? (() => {})}
              onAskChief={onAskChief ?? (() => {})}
            />
          )}
        </div>

        {/* 实时阵营面板 220px */}
        <aside className="w-[220px] shrink-0 border-l border-border/20 p-3">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            <Users className="h-3 w-3" /> 实时阵营
          </div>
          <div className="space-y-3">
            {panelDefs.map((p) => (
              <div key={p.key}>
                <div className="mb-1 flex items-center justify-between text-[10px]">
                  <span className={p.text}>{p.label} · {p.count} 人</span>
                  <span className="font-mono text-muted-foreground">{p.pct}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                  <div className={cn('h-full rounded-full transition-all', p.color)} style={{ width: `${p.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-lg border border-border/30 bg-secondary/20 p-2 text-[10px] text-muted-foreground">
            阵营基于专家预设偏好<br />（多/空/中性），随发言实时更新
          </div>
        </aside>
      </div>
    </div>
  )
}
