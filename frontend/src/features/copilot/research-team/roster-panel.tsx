/**
 * RESEARCH-TEAM-04: 阵容配置面板
 * 选择场景 / 团队预设 / 自定义专家组合 / 辩论轮数，并输入投研问题。
 */
'use client'

import React, { useMemo, useState } from 'react'
import { ChevronDown, Users, Sparkles, Target } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TEAM_GROUPS, SCENARIOS, expertById, type ExpertProfile } from './expert-roster'
import { AssetSearchBind } from './asset-search-bind'

export interface TeamConfig {
  scenario: string
  expertIds: string[]
  rounds: number
  /** 显式绑定的分析标的（标准 ticker，如 US.AAPL / HK.00700） */
  ticker?: string
  /** 绑定标的的展示名 */
  tickerName?: string
}

interface RosterPanelProps {
  question: string
  onQuestionChange: (v: string) => void
  config: TeamConfig
  onConfigChange: (c: TeamConfig) => void
  /** 选"自定义阵容"时点亮 */
  customMode: boolean
  onCustomModeChange: (v: boolean) => void
}

const ROUND_OPTIONS = [1, 2, 3]

export function RosterPanel({
  question,
  onQuestionChange,
  config,
  onConfigChange,
  customMode,
  onCustomModeChange,
}: RosterPanelProps) {
  const [teamOpen, setTeamOpen] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set(config.expertIds))

  const toggleExpert = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      onConfigChange({ ...config, expertIds: Array.from(next) })
      return next
    })
  }

  const scenarioExperts = useMemo(() => {
    // 选定场景时预置对应领域的默认阵容提示（前端镜像后端场景默认）
    const map: Record<string, string[]> = {
      financial_research: TEAM_GROUPS.flatMap((t) => (t.key === 'code' ? [] : t.members.map((m) => m.id))),
      full_investment: TEAM_GROUPS.flatMap((t) => (['code'].includes(t.key) ? [] : t.members.map((m) => m.id))),
      trade_decision: ['technical_analyst', 'trade_executor', 'risk_officer', 'sentiment_analyst', 'quant_researcher'],
      code_review: TEAM_GROUPS.find((t) => t.key === 'code')!.members.map((m) => m.id),
    }
    return map[config.scenario] ?? []
  }, [config.scenario])

  const effectiveRoster: ExpertProfile[] = (customMode ? Array.from(picked) : scenarioExperts)
    .map((id) => expertById(id))
    .filter((e): e is ExpertProfile => Boolean(e))

  return (
    <div className="space-y-3">
      {/* 场景选择 */}
      <div>
        <label className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Sparkles className="h-3 w-3" /> 投研场景
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                onConfigChange({ ...config, scenario: s.id })
                setPicked(new Set())
                onCustomModeChange(false)
              }}
              className={cn(
                'rounded-lg border px-2 py-1.5 text-left text-[11px] transition-colors',
                config.scenario === s.id
                  ? 'border-scene/60 bg-scene/10 text-foreground'
                  : 'border-white/10 text-muted-foreground hover:border-white/20 hover:text-foreground',
              )}
              title={s.desc}
            >
              <div className="font-semibold">{s.name}</div>
            </button>
          ))}
        </div>
      </div>

      {/* 阵容模式切换 */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            onCustomModeChange(false)
            setPicked(new Set())
          }}
          className={cn(
            'flex-1 rounded-md border px-2 py-1 text-[11px]',
            !customMode ? 'border-scene/50 bg-scene/10 text-foreground' : 'border-white/10 text-muted-foreground',
          )}
        >
          场景默认阵容
        </button>
        <button
          type="button"
          onClick={() => {
            onCustomModeChange(true)
            setPicked(new Set(scenarioExperts))
          }}
          className={cn(
            'flex-1 rounded-md border px-2 py-1 text-[11px]',
            customMode ? 'border-scene/50 bg-scene/10 text-foreground' : 'border-white/10 text-muted-foreground',
          )}
        >
          自定义组合
        </button>
      </div>

      {/* 自定义阵容：团队折叠 + 专家勾选 */}
      {customMode && (
        <div className="rounded-lg border border-white/10 bg-black/20 p-2">
          <button
            type="button"
            onClick={() => setTeamOpen((v) => !v)}
            className="flex w-full items-center justify-between text-[11px] font-medium text-muted-foreground"
          >
            <span className="flex items-center gap-1">
              <Users className="h-3 w-3" /> 从团队挑选（{picked.size} 已选）
            </span>
            <ChevronDown className={cn('h-3 w-3 transition-transform', teamOpen && 'rotate-180')} />
          </button>
          {teamOpen && (
            <div className="mt-2 space-y-2">
              {TEAM_GROUPS.map((g) => (
                <div key={g.key}>
                  <div className="mb-1 text-[10px] text-muted-foreground/80">{g.name}</div>
                  <div className="flex flex-wrap gap-1">
                    {g.members.map((m) => {
                      const on = picked.has(m.id)
                      return (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => toggleExpert(m.id)}
                          className={cn(
                            'rounded-full border px-2 py-0.5 text-[10px]',
                            on ? cn('bg-scene/15 text-scene', m.accent) : 'border-white/10 text-muted-foreground hover:border-white/25',
                          )}
                        >
                          {m.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 当前阵容预览 */}
      <div className="rounded-lg border border-white/10 bg-black/20 p-2">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          出战阵容 · {effectiveRoster.length} 人
        </div>
        <div className="flex flex-wrap gap-1">
          {effectiveRoster.length === 0 && (
            <span className="text-[10px] text-muted-foreground/60">未选择任何研究员</span>
          )}
          {effectiveRoster.map((m) => (
            <span
              key={m.id}
              className={cn('flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]', m.accent)}
            >
              <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-black/30 text-[8px] font-bold">
                {m.glyph}
              </span>
              {m.name}
            </span>
          ))}
        </div>
      </div>

      {/* 辩论轮数 */}
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          辩论轮数
        </label>
        <div className="flex gap-1.5">
          {ROUND_OPTIONS.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => onConfigChange({ ...config, rounds: r })}
              className={cn(
                'flex-1 rounded-md border px-2 py-1 text-[11px]',
                config.rounds === r
                  ? 'border-scene/60 bg-scene/10 text-foreground'
                  : 'border-white/10 text-muted-foreground hover:border-white/20',
              )}
            >
              {r} 轮
            </button>
          ))}
        </div>
      </div>

      {/* 标的绑定：显式指定分析标的，使 quote/fundamental/technicals 可采集 */}
      <div>
        <label className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <Target className="h-3 w-3" /> 分析标的
        </label>
        <AssetSearchBind
          value={config.ticker ?? ''}
          onChange={(ticker, name) => onConfigChange({ ...config, ticker, tickerName: name })}
        />
      </div>

      {/* 投研问题 */}
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          投研命题
        </label>
        <textarea
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          rows={3}
          placeholder="例如：AAPL 当前估值是否具备配置价值？结合基本面与技术面给出多空推演。"
          className="w-full resize-none rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 focus:border-scene/50 focus:outline-none"
        />
      </div>
    </div>
  )
}
