'use client'

import React from 'react'
import { cn } from '@/lib/utils'
import { Crown, Download, Save, RotateCcw, MessageSquare, TrendingUp, TrendingDown } from 'lucide-react'
import { BriefingMarkdown } from '@/features/briefing/briefing-markdown'
import type { ChiefReportEvent } from '@/features/copilot/research-team/expert-team-client'
import type { TeamConfig } from '@/features/copilot/research-team/roster-panel'

interface ChiefReportCardProps {
  event: ChiefReportEvent
  config: TeamConfig
  expertCount: number
  onSave: () => void
  onExport: () => void
  onRerun: () => void
  onAskChief: () => void
}

/** 概率仪表颜色：≥60 emerald / 40-60 gray / <40 red */
function gaugeColor(p: number): { stroke: string; text: string; label: string } {
  if (p >= 60) return { stroke: '#34d399', text: 'text-emerald-400', label: '看多倾向' }
  if (p < 40) return { stroke: '#f87171', text: 'text-red-400', label: '看空倾向' }
  return { stroke: '#94a3b8', text: 'text-slate-400', label: '中性' }
}

/** 半环概率仪表 */
function ProbabilityGauge({ value }: { value: number }) {
  const { stroke, text, label } = gaugeColor(value)
  const R = 42
  const C = Math.PI * R // 半圆弧长
  const filled = (Math.min(100, Math.max(0, value)) / 100) * C

  return (
    <div className="flex flex-col items-center">
      <div className="relative h-16 w-32">
        <svg viewBox="0 0 100 52" className="h-full w-full">
          <path d="M 8 50 A 42 42 0 0 1 92 50" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" strokeLinecap="round" />
          <path d="M 8 50 A 42 42 0 0 1 92 50" fill="none" stroke={stroke} strokeWidth="8" strokeLinecap="round" strokeDasharray={`${filled} ${C}`} />
        </svg>
        <div className={cn('absolute inset-x-0 bottom-0 text-center text-lg font-bold', text)}>{value}%</div>
      </div>
      <div className={cn('text-[10px]', text)}>{label}</div>
    </div>
  )
}

/**
 * COPILOT-17: B2 辩论室·收敛态 (Chief Report)
 *  居中 760px：概率仪表 / 结论摘要 / 分歧多空对照 / 元信息 / 操作行
 */
export function ChiefReportCard({ event, config, expertCount, onSave, onExport, onRerun, onAskChief }: ChiefReportCardProps) {
  const data = event.data
  const prob = data?.probability_assessment ?? event.bullish_probability ?? 50
  const consensus = data?.consensus_areas ?? []
  const divergence = data?.divergence_areas ?? []

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-4">
      {/* 报告卡 */}
      <div className="rounded-2xl border border-yellow-300/40 bg-gradient-to-b from-yellow-300/10 to-transparent p-5">
        {/* 头部：概率仪表 + 结论摘要 */}
        <div className="flex items-start gap-5">
          <ProbabilityGauge value={prob} />
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2">
              <Crown className="h-4 w-4 text-yellow-300" />
              <span className="text-xs font-bold text-yellow-300">首席投资官 · 最终研判</span>
            </div>
            <p className="text-xs leading-relaxed text-foreground/90">
              {data?.final_recommendation || (data?.strongest_bull_case && data?.strongest_bear_case
                ? `看多论据：${data.strongest_bull_case}；看空论据：${data.strongest_bear_case}`
                : '等待首席收敛报告…')}
            </p>
          </div>
        </div>

        {/* 关键分歧：多/空两列对照 */}
        {(data?.strongest_bull_case || data?.strongest_bear_case || divergence.length > 0) && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-emerald-400/20 bg-emerald-500/5 p-3">
              <div className="mb-1 flex items-center gap-1 text-[10px] font-bold text-emerald-400">
                <TrendingUp className="h-3 w-3" /> 多方观点
              </div>
              <p className="text-[11px] leading-relaxed text-emerald-100/80">{data?.strongest_bull_case || '—'}</p>
            </div>
            <div className="rounded-xl border border-red-400/20 bg-red-500/5 p-3">
              <div className="mb-1 flex items-center gap-1 text-[10px] font-bold text-red-400">
                <TrendingDown className="h-3 w-3" /> 空方观点
              </div>
              <p className="text-[11px] leading-relaxed text-red-100/80">{data?.strongest_bear_case || '—'}</p>
            </div>
          </div>
        )}

        {/* 完整报告（流式 Markdown） */}
        {event.content && (
          <div className="mt-4 border-t border-white/5 pt-4">
            <BriefingMarkdown content={event.content} />
          </div>
        )}

        {/* 风险提示 */}
        {data?.risk_warnings && data.risk_warnings.length > 0 && (
          <div className="mt-3 space-y-1 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
            <div className="text-[10px] font-bold text-amber-400">⚠️ 风险提示</div>
            {data.risk_warnings.map((r, i) => (
              <p key={i} className="text-[11px] text-amber-100/70">· {r}</p>
            ))}
          </div>
        )}

        {/* 元信息行 */}
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-3 text-[9px] font-mono text-muted-foreground">
          <span>专家 {expertCount} 人</span>
          <span>轮数 {config.rounds} 轮</span>
          <span>概率 {prob}%</span>
          <span className="ml-auto">Hermes Expert Team</span>
        </div>

        {/* 操作行 */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" onClick={onSave} className="flex items-center gap-1 rounded-lg border border-scene/40 bg-scene/10 px-2.5 py-1.5 text-[10px] text-scene hover:bg-scene/20 transition-colors">
            <Save className="h-3 w-3" /> 存入资产库
          </button>
          <button type="button" onClick={onExport} className="flex items-center gap-1 rounded-lg border border-border/40 px-2.5 py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition-colors">
            <Download className="h-3 w-3" /> 导出 Markdown
          </button>
          <button type="button" onClick={onRerun} className="flex items-center gap-1 rounded-lg border border-border/40 px-2.5 py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition-colors">
            <RotateCcw className="h-3 w-3" /> 调整阵容重跑
          </button>
          <button type="button" onClick={onAskChief} className="flex items-center gap-1 rounded-lg border border-border/40 px-2.5 py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition-colors">
            <MessageSquare className="h-3 w-3" /> 追问首席
          </button>
        </div>
      </div>
    </div>
  )
}
