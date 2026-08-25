import React, { useState, useEffect, useRef } from 'react'
import { Check, Loader2, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChatMessage } from './types'

type Phase = 'plan' | 'tool' | 'verify' | 'output'

interface PhaseDef {
  key: Phase
  label: string
  labelEn: string
}

const PHASES: PhaseDef[] = [
  { key: 'plan', label: '规划', labelEn: 'Plan' },
  { key: 'tool', label: '调用工具', labelEn: 'Tool' },
  { key: 'verify', label: '核验', labelEn: 'Verify' },
  { key: 'output', label: '输出', labelEn: 'Output' },
]

/** 从消息状态推导当前阶段 */
function derivePhase(msg: ChatMessage, isLast: boolean, isGenerating: boolean): Phase {
  if (!isGenerating || !isLast) return 'output'
  const hasThinkContent = msg.content.includes('<think>') || msg.thinkEndTime || Boolean(msg.reasoning)
  const hasTools = (msg.tools?.length ?? 0) > 0
  const allToolsDone = hasTools && msg.tools!.every(t => t.status === 'done')
  const hasOutputText = msg.thinkEndTime && msg.content.replace(/<think>[\s\S]*?(?:<\/think>|$)/, '').trim().length > 0

  if (hasOutputText) return 'output'
  if (allToolsDone) return 'verify'
  if (hasTools) return 'tool'
  if (hasThinkContent || msg.content.length > 0) return 'plan'
  return 'plan'
}

/**
 * COPILOT-03: 思维链四阶段进度器。
 * 消费真实 SSE 事件驱动的阶段状态，30s 无事件显示 amber 慢响应警告。
 */
export function ThinkingProgress({
  msg,
  isLast,
  isGenerating,
}: {
  msg: ChatMessage
  isLast: boolean
  isGenerating: boolean
}) {
  const currentPhase = derivePhase(msg, isLast, isGenerating)
  const [lastEventTime] = useState(Date.now())
  const [stale, setStale] = useState(false)
  // P0-4: 推理片段默认折叠，用户可展开查看真实推理过程
  const [reasoningOpen, setReasoningOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 💡 30s 无新事件 → amber 慢响应警告
  useEffect(() => {
    if (!isGenerating || !isLast) {
      setStale(false)
      return
    }
    timerRef.current = setInterval(() => {
      if (Date.now() - lastEventTime > 30_000) {
        setStale(true)
      }
    }, 5_000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [isGenerating, isLast, lastEventTime])

  // 流结束后清除 stale
  useEffect(() => {
    if (!isGenerating) setStale(false)
  }, [isGenerating])

  const phaseIdx = PHASES.findIndex(p => p.key === currentPhase)

  return (
    <div className="flex flex-col gap-2">
      {/* 四阶段横向进度条 */}
      <div className="flex items-center gap-0.5">
        {PHASES.map((phase, i) => {
          const isActive = i === phaseIdx
          const isDone = i < phaseIdx
          return (
            <React.Fragment key={phase.key}>
              {i > 0 && (
                <div className={cn(
                  'flex-1 h-px transition-colors duration-500',
                  isDone ? 'bg-emerald-500/60' : 'bg-border/40'
                )} />
              )}
              <div className={cn(
                'flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium transition-all duration-300',
                isDone && 'bg-emerald-500/10 text-emerald-500',
                isActive && !stale && 'bg-purple-500/10 text-purple-400',
                isActive && stale && 'bg-amber-500/10 text-amber-500',
                !isActive && !isDone && 'text-muted-foreground/50',
              )}>
                {isDone ? (
                  <Check className="h-3 w-3" />
                ) : isActive ? (
                  stale ? (
                    <AlertTriangle className="h-3 w-3" />
                  ) : (
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-purple-500" />
                    </span>
                  )
                ) : (
                  <span className="h-2.5 w-2.5 rounded-full bg-border/40" />
                )}
                <span>{phase.label}</span>
                <span className="text-[8px] opacity-60 hidden sm:inline">{phase.labelEn}</span>
              </div>
            </React.Fragment>
          )
        })}
      </div>

      {/* P0-4: Plan 阶段真实推理片段（reasoning_chunk 流），默认折叠 */
      currentPhase === 'plan' && msg.reasoning && (
        <div className="rounded-lg border border-purple-500/20 bg-purple-500/5">
          <button
            type="button"
            onClick={() => setReasoningOpen(v => !v)}
            className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-purple-400 hover:text-purple-300 transition-colors"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-purple-500" />
            </span>
            推理过程
            <span className="text-muted-foreground/60">({msg.reasoning.length} 字)</span>
            <span className="ml-auto">{reasoningOpen ? '收起' : '展开'}</span>
          </button>
          {reasoningOpen && (
            <div className="px-2.5 pb-2 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap max-h-40 overflow-y-auto custom-scrollbar">
              {msg.reasoning}
            </div>
          )}
        </div>
      )}

      {/* 工具 chip 行：当前处于 Tool 阶段时展示正在执行的工具 */}
      {currentPhase === 'tool' && msg.tools && msg.tools.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {msg.tools.map((tool, i) => (
            <span
              key={i}
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border transition-all',
                tool.status === 'running'
                  ? 'border-purple-500/30 bg-purple-500/10 text-purple-400'
                  : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500'
              )}
            >
              {tool.status === 'running' && <Loader2 className="h-2.5 w-2.5 animate-spin" />}
              {tool.name}
            </span>
          ))}
        </div>
      )}

      {/* 30s 慢响应警告文案 */}
      {stale && (
        <div className="text-[10px] text-amber-500 flex items-center gap-1">
          <AlertTriangle className="h-3 w-3" />
          响应缓慢，后端可能排队中…
        </div>
      )}
    </div>
  )
}
