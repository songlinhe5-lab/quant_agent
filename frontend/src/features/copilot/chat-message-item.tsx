/**
 * COPILOT-11: 消息气泡主编排壳 (600 → ~180 行)
 * 子组件拆分:
 *   - markdown-error-boundary.tsx  (错误边界)
 *   - code-block-renderer.tsx      (代码块渲染)
 *   - markdown-components.tsx      (ReactMarkdown 配置工厂)
 *   - tool-results-panel.tsx       (思考过程 + 工具结果)
 *   - strategy-blocks.tsx          (策略部署卡片)
 */
import React, { useRef, useState, useEffect, useCallback } from 'react'
import { User, Bot, Loader2, ChevronRight, ChevronDown, ChevronUp, FileText, Check, Copy, RotateCcw, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ThinkingProgress } from '@/features/copilot/thinking-progress'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { ChatMessage } from './types'
import { MarkdownErrorBoundary } from './markdown-error-boundary'
import { ToolResultsPanel } from './tool-results-panel'
import { StrategyBlocks } from './strategy-blocks'
import { useMarkdownComponents } from './markdown-components'

export const ChatMessageItem = React.memo(({
  msg, idx, isLast, isGenerating, copiedIndex, onCopy, onRetry, onSend,
}: {
  msg: ChatMessage; idx: number; isLast: boolean; isGenerating: boolean
  copiedIndex: number | null
  onCopy: (text: string, idx: number) => void
  onRetry: (idx: number) => void
  onSend: (text: string) => void
}) => {
  const content = msg.content || ''
  let thinkContent = ''
  let finalContent = content

  const thinkStart = content.indexOf('<think>')
  const thinkEnd = content.indexOf('</think>')
  if (thinkStart !== -1) {
    if (thinkEnd !== -1) {
      thinkContent = content.substring(thinkStart + 7, thinkEnd).trim()
      finalContent = (content.substring(0, thinkStart) + content.substring(thinkEnd + 8)).trim()
    } else {
      thinkContent = content.substring(thinkStart + 7).trim()
      finalContent = content.substring(0, thinkStart).trim()
    }
  }

  // 💡 第一层防御：智能补全未闭合的代码块标签
  const codeBlockMatches = finalContent.match(/(?:^|\n)\s*```/g)
  if (codeBlockMatches && codeBlockMatches.length % 2 !== 0) {
    finalContent += '\n\n```'
  }

  const hasTools = Boolean(msg.tools && msg.tools.length > 0)
  const hasThinking = Boolean(thinkContent)
  const isThinkingState = isGenerating && isLast && thinkStart !== -1 && thinkEnd === -1
  const hasRunningTools = Boolean(msg.tools?.some(t => t.status === 'running'))

  // 💡 深度思考内容自动滚动到底部
  const thinkContentRef = useRef<HTMLDivElement>(null)
  const thinkUserScrolledRef = useRef(false)
  useEffect(() => {
    if (isThinkingState && thinkContentRef.current && !thinkUserScrolledRef.current) {
      thinkContentRef.current.scrollTop = thinkContentRef.current.scrollHeight
    }
  }, [thinkContent, isThinkingState])
  const handleThinkScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const t = e.currentTarget
    thinkUserScrolledRef.current = !(t.scrollHeight - t.scrollTop - t.clientHeight < 50)
  }, [])

  const mdComponents = useMarkdownComponents({ onSend, isGenerating })

  return (
    <div
      className={cn('flex gap-4 max-w-4xl mx-auto w-full animate-in slide-in-from-bottom-2 fade-in duration-300', msg.role === 'user' ? 'flex-row-reverse' : 'flex-row')}
      style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 200px' }}
    >
      <div className={cn('h-8 w-8 rounded-lg shrink-0 flex items-center justify-center border shadow-sm mt-1', msg.role === 'user' ? 'bg-primary/20 border-primary/30 text-primary' : 'bg-emerald-500/20 border-emerald-500/30 text-emerald-400')}>
        {msg.role === 'user' ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={cn('px-5 py-4 rounded-2xl text-sm leading-relaxed', msg.role === 'user' ? 'bg-primary/10 border border-primary/20 text-foreground rounded-tr-sm shadow-sm' : 'bg-card border border-border/40 text-foreground rounded-tl-sm shadow-sm dark:shadow-[0_0_15px_rgba(0,0,0,0.5)]', msg.role === 'assistant' && 'min-w-[280px] max-w-full overflow-hidden')}>

        {msg.role === 'user' ? (
          <div className="flex flex-col gap-2">
            <div className="whitespace-pre-wrap font-mono">{msg.content}</div>
            {msg.attachments && msg.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-1">
                {msg.attachments.map((att, i) => (
                  <div key={i} className="flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 p-1.5 rounded-lg max-w-xs">
                    {att.type.startsWith('image/') ? (
                      <img src={att.url} alt={att.name} className="h-10 w-10 object-cover rounded shadow-sm border border-indigo-500/20" />
                    ) : (
                      <div className="h-10 w-10 flex items-center justify-center bg-indigo-500/20 rounded border border-indigo-500/30">
                        <FileText className="h-5 w-5 text-indigo-500" />
                      </div>
                    )}
                    <span className="text-[10px] text-indigo-700 dark:text-indigo-300 truncate font-semibold px-1">{att.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col">
            {/* COPILOT-09: 迭代上限已达——降级兜底总结提示条 */}
            {msg.iterationLimitReached && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>已达 <strong>8</strong> 步推理上限，以下为降级模型兜底总结，结论可能不完整。</span>
              </div>
            )}
            {/* COPILOT-03: 生成中 → 四阶段进度器；完成后 → 可折叠思考过程面板 */}
            {isGenerating && isLast ? (
              <ThinkingProgress msg={msg} isLast={isLast} isGenerating={isGenerating} />
            ) : (hasThinking || hasTools) ? (
              <ToolResultsPanel msg={msg} isGenerating={isGenerating} isLast={isLast} thinkContent={thinkContent} hasThinking={hasThinking} hasTools={hasTools} hasRunningTools={hasRunningTools} />
            ) : null}

            <div className="markdown-body">
              <MarkdownErrorBoundary fallbackContent={finalContent}>
                <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { strict: false }]]} components={mdComponents}>
                  {finalContent}
                </ReactMarkdown>
              </MarkdownErrorBoundary>

              {/* 💡 策略部署卡片 */}
              {msg.strategyBlocks && msg.strategyBlocks.length > 0 && <StrategyBlocks blocks={msg.strategyBlocks} />}

              {isGenerating && isLast && !isThinkingState && (
                <span className="inline-block w-1.5 h-4 mt-2 align-middle bg-emerald-400 animate-pulse" />
              )}

              {!isThinkingState && (finalContent || !isGenerating) && (
                <div className="flex items-center gap-2 mt-4 pt-3 border-t border-border/30 text-muted-foreground select-none">
                  <button onClick={() => onCopy(finalContent, idx)} className="flex items-center gap-1.5 text-[10px] hover:text-foreground transition-colors px-1.5 py-1 rounded-md hover:bg-secondary/60" title="复制内容">
                    {copiedIndex === idx ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                    <span>{copiedIndex === idx ? '已复制' : '复制'}</span>
                  </button>
                  {isLast && (
                    <button onClick={() => onRetry(idx)} disabled={isGenerating} className="flex items-center gap-1.5 text-[10px] hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed px-1.5 py-1 rounded-md hover:bg-secondary/60" title="重新生成">
                      <RotateCcw className={cn('h-3 w-3', isGenerating && 'animate-spin')} />
                      <span>重试</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}, (prev, next) => {
  return (
    prev.msg === next.msg &&
    prev.isLast === next.isLast &&
    prev.isGenerating === next.isGenerating &&
    prev.copiedIndex === next.copiedIndex
  )
})
