/**
 * COPILOT-11: 思考过程面板（含工具结果展示）
 * 可折叠 <details> 容器，展示 think 内容 + 工具调用链。
 * 从 chat-message-item.tsx 拆出，原 ~140 行 JSX。
 */
import React, { useRef, useEffect, useCallback } from 'react'
import { Loader2, Sparkles, ChevronRight, Search, Globe, Database, FileText, Code2, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ThinkTimer } from '@/features/copilot/think-timer'
import type { ChatMessage, ToolStep } from './types'

// COPILOT-21: 取数时间 STALE 判定
// 行情类(5分钟) / 基本面类(1日) 超时视为过期
function isStale(tool: ToolStep): boolean {
  if (!tool.timestamp) return false
  const tName = tool.name.toLowerCase()
  const elapsed = Date.now() - tool.timestamp
  if (tName.includes('market') || tName.includes('quote') || tName.includes('price')) return elapsed > 5 * 60 * 1000
  if (tName.includes('fundamental') || tName.includes('valuation') || tName.includes('profile') || tName.includes('financial')) return elapsed > 24 * 60 * 60 * 1000
  return false
}

function fmtTs(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function ToolResultItem({ tool, tIdx }: { tool: ToolStep; tIdx: number }) {
  const tName = tool.name.toLowerCase()
  const isSearch = tName.includes('search')
  const isNews = tName.includes('news')
  const isMarket = tName.includes('market') || tName.includes('quote')
  const isBrowse = tName.includes('browse') || tName.includes('read')
  const ToolIcon = isSearch ? Search : isNews ? Globe : isMarket ? Database : isBrowse ? FileText : Code2
  const stale = isStale(tool)
  // COPILOT-22: 交易执行类工具（真实下单能力）标红边警示
  const isTradeExec = tName.includes('manage_broker_orders') || tName.includes('broker_orders') || tName.includes('trade_execute')

  let actionName = '调用工具'
  if (isSearch) actionName = '搜索网络'
  else if (isNews) actionName = '检索资讯'
  else if (isMarket) actionName = '获取行情'
  else if (isBrowse) actionName = '阅读网页'

  let queryDesc = tool.input
  try {
    const parsed = JSON.parse(tool.input)
    const key = ['query', 'q', 'ticker', 'keyword', 'url'].find(k => parsed[k])
    if (key && typeof parsed[key] === 'string') queryDesc = parsed[key]
  } catch (_e) { /* ignore */ }

  let resultList: any[] | null = null
  try {
    if (tool.result) {
      const parsed = JSON.parse(tool.result)
      if (Array.isArray(parsed)) resultList = parsed
      else if (parsed && Array.isArray(parsed.data)) resultList = parsed.data
      else if (parsed && Array.isArray(parsed.results)) resultList = parsed.results
    }
  } catch (_e) { /* ignore */ }

  return (
    <div key={tIdx} className={cn('border rounded-md p-2 bg-slate-100/50 dark:bg-zinc-900/50', tool.status === 'error' ? 'border-red-400/40' : 'border-border/30', isTradeExec && 'border-l-2 border-l-red-400', stale && 'opacity-60 saturate-50')}>
      <div className="flex items-center gap-1.5 mb-1 text-[11px] font-bold text-slate-700 dark:text-slate-300">
        {tool.status === 'running' ? <Loader2 className="h-3 w-3 animate-spin text-primary" /> : tool.status === 'error' ? <AlertTriangle className="h-3 w-3 text-red-400" /> : <ToolIcon className="h-3 w-3 text-emerald-500" />}
        {actionName} {tool.name !== actionName && <span className="font-mono text-[9px] text-muted-foreground">({tool.name})</span>}
        {queryDesc && queryDesc !== '{}' && <span className="text-muted-foreground font-normal truncate max-w-[200px]"> - {queryDesc}</span>}
        {/* COPILOT-21: 取数时间戳 + STALE 角标 */}
        {tool.timestamp && tool.status !== 'running' && (
          <span className="ml-auto shrink-0 font-mono text-[9px] text-muted-foreground">取数 {fmtTs(tool.timestamp)}</span>
        )}
        {stale && (
          <span className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-1 py-px text-[8px] font-bold text-amber-500" title="数据已超过有效期，以下结论可能基于过期数据">STALE</span>
        )}
      </div>

      {/* COPILOT-21: 工具失败 → 红色失败块，禁止估计值兜底 */}
      {tool.status === 'error' ? (
        <div className="mt-1.5 rounded-md border border-red-400/30 bg-red-500/10 px-2 py-1.5 text-[10px] text-red-400">
          <div className="font-bold">数据获取失败：{tool.errorMessage || '未知原因'}</div>
          <div className="mt-0.5 text-red-300/80">以下结论不含该项数据</div>
        </div>
      ) : tool.status === 'done' && (
        <div className="mt-1.5 pt-1.5 border-t border-border/40">
          <div className="text-[10px] text-muted-foreground mb-1 font-medium">
            {resultList ? `✅ ${isBrowse ? '浏览了' : '获取到'} ${resultList.length} ${isBrowse ? '个页面' : isNews ? '篇资讯' : '条数据'}` : '✅ 执行完毕'}
          </div>
          <details className="group/tool mt-1">
            <summary className="text-[10px] text-slate-500 cursor-pointer hover:text-primary transition-colors flex items-center gap-1 w-fit select-none">
              查看详细内容 <ChevronRight className="h-3 w-3 transition-transform group-open/tool:rotate-90" />
            </summary>
            <div className="mt-2 max-h-40 overflow-y-auto custom-scrollbar bg-white dark:bg-black/40 p-1.5 rounded border border-border/50">
              {resultList && resultList.length > 0 && (resultList[0].title || resultList[0].headline || resultList[0].name) ? (
                <div className="flex flex-col gap-1.5">
                  {resultList.map((item, i) => {
                    const title = item.title || item.headline || item.name
                    const url = item.url || item.link
                    const sentiment = item.sentiment
                    if (sentiment) {
                      const isBullish = sentiment.label === 'Bullish'
                      const isBearish = sentiment.label === 'Bearish'
                      const tagColor = isBullish ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'
                        : isBearish ? 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20'
                          : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20'
                      return (
                        <div key={i} className="border border-border/50 rounded flex flex-col p-2 bg-slate-50 dark:bg-black/30 hover:bg-slate-100 dark:hover:bg-black/50 transition-colors">
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <div className="font-semibold text-[11px] text-foreground line-clamp-1" title={sentiment.summary_zh || title}>
                              {url ? <a href={url} target="_blank" className="hover:underline">{sentiment.summary_zh || title}</a> : (sentiment.summary_zh || title)}
                            </div>
                            <div className={cn('text-[9px] px-1.5 py-0.5 rounded border whitespace-nowrap flex items-center gap-1 font-mono', tagColor)}>
                              {isBullish ? '🟢' : isBearish ? '🔴' : '⚪'} {sentiment.label} ({sentiment.score})
                            </div>
                          </div>
                          <div className="text-[10px] text-muted-foreground line-clamp-1 mb-1.5" title={title}>{title}</div>
                          <div className="text-[10px] text-slate-600 dark:text-slate-400 bg-secondary/40 px-2 py-1.5 rounded-sm border border-border/30 line-clamp-2" title={sentiment.reasoning}>
                            <span className="font-bold">💡 研判: </span>{sentiment.reasoning}
                          </div>
                        </div>
                      )
                    }
                    return (
                      <div key={i} className="text-[10px] text-slate-600 dark:text-gray-400 line-clamp-1 flex items-center gap-1.5 before:content-['•'] before:text-slate-400 px-1">
                        {url ? <a href={url} target="_blank" className="hover:text-primary hover:underline" title={title}>{title}</a> : <span title={title}>{title}</span>}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <code className="text-[10px] font-mono text-slate-600 dark:text-gray-400 whitespace-pre-wrap break-all">{tool.result || '无数据返回'}</code>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

export function ToolResultsPanel({
  msg, isGenerating, isLast, thinkContent, hasThinking, hasTools, hasRunningTools,
}: {
  msg: ChatMessage
  isGenerating: boolean
  isLast: boolean
  thinkContent: string
  hasThinking: boolean
  hasTools: boolean
  hasRunningTools: boolean
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null)
  const userToggledRef = useRef(false)
  const hasAutoExpandedRef = useRef(false)
  const shouldAutoExpand = (isGenerating && isLast && !!(thinkContent)) || hasRunningTools

  useEffect(() => {
    if (shouldAutoExpand && !userToggledRef.current && !hasAutoExpandedRef.current && detailsRef.current) {
      detailsRef.current.open = true
      hasAutoExpandedRef.current = true
    }
  }, [shouldAutoExpand])

  const handleThinkToggle = useCallback(() => { userToggledRef.current = true }, [])

  return (
    <details ref={detailsRef} onToggle={handleThinkToggle} className="group border border-border/30 rounded-lg overflow-hidden bg-slate-50/50 dark:bg-black/20 text-xs transition-colors mb-3">
      <summary className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-100 dark:hover:bg-white/5 font-semibold select-none list-none transition-colors [&::-webkit-details-marker]:hidden">
        {hasRunningTools ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : <Sparkles className="h-3.5 w-3.5 text-slate-500" />}
        <span className="text-slate-600 dark:text-gray-300">思考过程</span>
        {msg.startTime && msg.thinkEndTime && (
          <span className="text-[10px] text-muted-foreground ml-1">(<ThinkTimer startTime={msg.startTime} endTime={msg.thinkEndTime} />)</span>
        )}
        <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground transition-transform duration-200 group-open:rotate-90" />
      </summary>
      <div className="px-3 pb-3 pt-2 border-t border-border/20 text-muted-foreground whitespace-pre-wrap break-all bg-white dark:bg-black/40 max-h-96 overflow-y-auto custom-scrollbar">
        {hasThinking && <div className="italic text-slate-500 dark:text-slate-400 mb-3 last:mb-0">{thinkContent}</div>}
        {hasTools && (
          <div className="flex flex-col gap-2">
            {msg.tools!.map((tool, tIdx) => <ToolResultItem key={tIdx} tool={tool} tIdx={tIdx} />)}
          </div>
        )}
      </div>
    </details>
  )
}
