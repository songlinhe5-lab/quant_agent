'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Scale, Play, Sparkles, Target, Loader2, AlertTriangle } from 'lucide-react'
import { SCENARIOS, TEAM_GROUPS, expertById, scenarioDefaultExperts, type ExpertProfile } from '@/features/copilot/research-team/expert-roster'

/** 后端 GET /expert-team/scenarios 返回的场景模板 */
interface ApiScenario {
  id: string
  name: string
  domain: string
}

export interface ComposerResult {
  question: string
  scenario: string
  expertIds: string[]
  rounds: number
  /** 声明式分析标的（可选，如 ["阅文集团","腾讯"]） */
  symbols?: string[]
}

interface DebateComposerProps {
  /** 发起投研会：回传配置 */
  onLaunch: (result: ComposerResult) => void
  /** 生成当前持仓命题（预留，COPILOT 资产库接入后启用） */
  onUseHoldings?: () => void
}

const ROUND_OPTIONS = [1, 2, 3]

// 场景默认阵容（镜像集中在 expert-roster.ts，与后端场景模板一致）
const SCENARIO_DEFAULT_EXPERTS: Record<string, string[]> = Object.fromEntries(
  SCENARIOS.map((s) => [s.id, s.expertIds]),
)

/**
 * COPILOT-15: B2 辩论室·组局态 (Proposition Composer)
 *  四组配置居中 720px：命题 textarea / 场景卡片 / 专家网格 / 轮数分段
 *  场景数据来自 GET /expert-team/scenarios，静态镜像做 desc 兜底并标角标
 */
export function DebateComposer({ onLaunch, onUseHoldings }: DebateComposerProps) {
  const [question, setQuestion] = useState('')
  const [scenario, setScenario] = useState('financial_research')
  const [picked, setPicked] = useState<Set<string>>(() => new Set(SCENARIO_DEFAULT_EXPERTS.financial_research))
  const [rounds, setRounds] = useState(2)
  const [apiScenarios, setApiScenarios] = useState<ApiScenario[] | null>(null)
  // 声明式分析标的（可留空：留空时由后端从命题文本/LLM 推导）
  const [symbolInput, setSymbolInput] = useState('')
  const declaredSymbols = useMemo(
    () => symbolInput.split(/[，,、\s]+/).map((s) => s.trim()).filter(Boolean),
    [symbolInput],
  )

  // 场景：接口为主，静态镜像兜底
  useEffect(() => {
    let mounted = true
    apiClient.get('/expert-team/scenarios')
      .then((res: any) => { if (mounted && Array.isArray(res?.data?.scenarios)) setApiScenarios(res.data.scenarios) })
      .catch(() => { /* 兜底用静态镜像 */ })
    return () => { mounted = false }
  }, [])

  const scenarios = useMemo(() => {
    if (!apiScenarios?.length) return SCENARIOS
    // 用接口场景（id/name/domain），desc 从静态镜像补，保证展示完整
    return SCENARIOS.map((s) => {
      const api = apiScenarios.find((a) => a.id === s.id)
      return api ? { ...s, name: api.name } : s
    })
  }, [apiScenarios])

  const fromApi = Boolean(apiScenarios?.length)

  // 切换场景：重设默认阵容（代码域 4 人仅在代码审查场景出现）
  const selectScenario = (id: string) => {
    setScenario(id)
    setPicked(new Set(SCENARIO_DEFAULT_EXPERTS[id] ?? []))
  }

  const toggleExpert = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 出站阵容：非代码场景排除代码域，代码审查仅代码域
  const eligibleExperts = useMemo(() => {
    const isCode = scenario === 'code_review'
    return TEAM_GROUPS
      .flatMap((g) => g.members)
      .filter((e) => (isCode ? e.team === 'code' : e.team !== 'code'))
  }, [scenario])

  const effectiveRoster = useMemo(() =>
    Array.from(picked).map((id) => expertById(id)).filter((e): e is ExpertProfile => Boolean(e)),
  [picked])

  const canLaunch = question.trim().length > 0 && effectiveRoster.length > 0
  const estSeconds = effectiveRoster.length * rounds * 20

  return (
    <div className="flex h-full flex-col items-center overflow-y-auto custom-scrollbar">
      <div className="w-full max-w-[720px] px-6 py-6 space-y-5">
        {/* 标题 */}
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-[#A78BFA]" />
          <h2 className="text-sm font-semibold text-foreground">发起投研会</h2>
          <span className="text-[10px] text-muted-foreground">组局 · Proposition Composer</span>
        </div>

        {/* ① 投研命题 */}
        <div>
          <label className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Target className="h-3 w-3" /> 投研命题
          </label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="例如：AAPL 当前估值是否具备配置价值？结合基本面、技术面与宏观，给出多空推演与置信度。"
            className="w-full resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:border-[#A78BFA]/50 focus:outline-none transition-colors"
          />
          <button
            type="button"
            disabled
            onClick={onUseHoldings}
            className="mt-1 flex cursor-not-allowed items-center gap-1 text-[10px] text-muted-foreground/60"
            title="资产库接入后开放"
          >
            <Sparkles className="h-3 w-3" /> 从当前持仓生成 <span className="rounded border border-white/10 px-1 text-[8px]">即将开放</span>
          </button>
        </div>

        {/* ①-b 分析标的（声明式，可选） */}
        <div>
          <label className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Target className="h-3 w-3" /> 分析标的
            <span className="text-[9px] normal-case text-muted-foreground/60">（可选，留空则由 AI 从命题推导）</span>
          </label>
          <input
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            placeholder="如：阅文集团, 腾讯, US.AAPL（逗号/空格分隔，可填中文名或代码）"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 focus:border-[#A78BFA]/50 focus:outline-none transition-colors"
          />
          {declaredSymbols.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {declaredSymbols.map((s) => (
                <span key={s} className="rounded-full border border-[#A78BFA]/40 bg-[#A78BFA]/10 px-2 py-0.5 text-[10px] text-[#A78BFA]">
                  {s}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ② 投研场景 4 卡 */}
        <div>
          <label className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Sparkles className="h-3 w-3" /> 投研场景
            {!fromApi && (
              <span className="flex items-center gap-0.5 rounded border border-amber-500/30 bg-amber-500/10 px-1 py-px text-[8px] text-amber-400" title="场景接口不可用，当前使用前端静态镜像">
                <AlertTriangle className="h-2.5 w-2.5" /> 兜底
              </span>
            )}
          </label>
          <div className="grid grid-cols-2 gap-2">
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => selectScenario(s.id)}
                className={cn(
                  'rounded-xl border px-3 py-2 text-left transition-colors',
                  scenario === s.id
                    ? 'border-[#A78BFA]/60 bg-[#A78BFA]/10'
                    : 'border-white/10 hover:border-white/25',
                )}
              >
                <div className={cn('text-xs font-semibold', scenario === s.id ? 'text-[#A78BFA]' : 'text-foreground')}>{s.name}</div>
                <div className="mt-0.5 text-[9px] text-muted-foreground/80 line-clamp-1">{s.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* ③ 出战阵容：专家网格 */}
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            出战阵容 · {effectiveRoster.length} 人（点击勾选 / 取消）
          </label>
          <div className="flex flex-wrap gap-1.5">
            {eligibleExperts.map((e) => {
              const on = picked.has(e.id)
              return (
                <button
                  key={e.id}
                  type="button"
                  onClick={() => toggleExpert(e.id)}
                  title={e.description}
                  className={cn(
                    'flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] transition-colors',
                    on ? cn('border-[#A78BFA]/50 bg-[#A78BFA]/15', e.accent.split(' ')[0]) : 'border-white/10 text-muted-foreground hover:border-white/25',
                  )}
                >
                  <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-black/30 text-[8px] font-bold">{e.glyph}</span>
                  {e.name}
                </button>
              )
            })}
          </div>
          {effectiveRoster.length === 0 && (
            <p className="mt-1 text-[10px] text-red-400/80">请至少选择一位专家</p>
          )}
        </div>

        {/* ④ 辩论轮数分段 */}
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            辩论轮数
          </label>
          <div className="flex gap-1.5">
            {ROUND_OPTIONS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRounds(r)}
                className={cn(
                  'flex-1 rounded-lg border px-2 py-1.5 text-[11px] transition-colors',
                  rounds === r ? 'border-[#A78BFA]/60 bg-[#A78BFA]/10 text-[#A78BFA]' : 'border-white/10 text-muted-foreground hover:border-white/25',
                )}
              >
                {r} 轮
              </button>
            ))}
          </div>
        </div>

        {/* 底部 CTA + 预估耗时 */}
        <div className="pt-2">
          <button
            type="button"
            disabled={!canLaunch}
            onClick={() => {
              // 阵容未改时不传 expert_ids，由后端场景模板决定（保证前后端阵容一致）
              const pickedIds = effectiveRoster.map((e) => e.id)
              const defaults = scenarioDefaultExperts(scenario)
              const customized = pickedIds.length !== defaults.length || pickedIds.some((id) => !defaults.includes(id))
              onLaunch({ question, scenario, expertIds: customized ? pickedIds : [], rounds, symbols: declaredSymbols })
            }}
            className={cn(
              'flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold transition-all',
              canLaunch
                ? 'bg-[#A78BFA] text-black hover:opacity-90 shadow-[0_0_15px_rgba(167,139,250,0.3)]'
                : 'cursor-not-allowed bg-white/5 text-muted-foreground',
            )}
          >
            <Play className="h-3.5 w-3.5" /> 发起投研会
          </button>
          <p className="mt-2 text-center text-[10px] text-muted-foreground">
            ≈ 预估耗时 {estSeconds}s · 专家数 {effectiveRoster.length} × 轮数 {rounds} × 20s
            <span className="ml-1 text-muted-foreground/50">（估算）</span>
          </p>
        </div>
      </div>
    </div>
  )
}
