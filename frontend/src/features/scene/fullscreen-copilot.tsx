'use client'

import React, { useContext, useState, useEffect } from 'react'
import { Brain, History, Plus, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ChatProvider, ChatActionContext } from '@/features/copilot/chat-context'
import { ChatSidebarWrapper } from '@/features/copilot/chat-sidebar-wrapper'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'
import { useMarketStore } from '@/stores/marketStore'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'

/** PROD-04b: AI 分析模式快捷指令定义 */
interface AiQuickCommand {
  key: string
  emoji: string
  label: string
  /** 是否需要内联当前聚焦标的 ticker */
  ticker: boolean
  template: string
}

const AI_QUICK_COMMANDS: AiQuickCommand[] = [
  {
    key: 'morning',
    emoji: '🌤️',
    label: '今日早报',
    ticker: false,
    template:
      '请生成今日盘前推演早报，调用宏观新闻与行情工具，汇总全球宏观高危事件、核心标的监控与多空研判，并生成内联数据卡片。',
  },
  {
    key: 'compare',
    emoji: '⚖️',
    label: '对比分析',
    ticker: true,
    template:
      '请对比分析 {symbol} 与同行业 top 3 竞品，调用行情与基本面工具，从估值、技术面与资金面给出差异化研判，并生成内联对比图表。',
  },
  {
    key: 'option',
    emoji: '📡',
    label: '期权链',
    ticker: true,
    template:
      '请拉取 {symbol} 的期权链 (OPTION_CHAIN)，分析隐含波动率曲面与多空持仓结构，给出期权策略建议，并生成内联图表。',
  },
  {
    key: 'macro',
    emoji: '🌐',
    label: '宏观雷达',
    ticker: false,
    template:
      '请扫描当前全球宏观高危事件与情绪雷达（VIX、P/C Ratio、利率、FRED 数据），调用宏观工具给出风险推演，并生成内联图表。',
  },
  {
    key: 'watchlist',
    emoji: '📋',
    label: '查询自选',
    ticker: false,
    template:
      '请列出我的自选股池，调用行情工具做整体强弱扫描、异动提示与板块分布，并生成内联数据卡片。',
  },
]

/**
 * PROD-04: AI 分析模式全屏对话工作台
 * 复用 ChatProvider + MessageListArea + ChatInputBox，全宽布局。
 * PROD-04b: 补充快捷指令栏 + 进入时自动携带当前聚焦标的 ticker（上下文感知）。
 */
function FullscreenCopilotChrome() {
  const { handleNewChat, handleSend } = useContext(ChatActionContext)
  const [sessionsOpen, setSessionsOpen] = useState(false)

  // PROD-04b: 进入 AI 分析模式时，将全局当前聚焦标的注入副驾上下文（实现跨模式 ticker 携带）
  useEffect(() => {
    const ticker = useMarketStore.getState().currentTicker
    if (ticker) {
      const prev = useCopilotContextStore.getState().context
      useCopilotContextStore.getState().setContext({
        kind: 'analysis',
        title: prev?.title ?? 'AI 分析模式',
        summary: prev?.summary ?? `当前聚焦标的: ${ticker}`,
        symbol: ticker,
      })
    }
  }, [])

  const runCommand = (cmd: AiQuickCommand) => {
    const ticker = useMarketStore.getState().currentTicker
    const prompt = cmd.ticker ? cmd.template.replace(/\{symbol\}/g, ticker || '当前聚焦标的') : cmd.template
    // 快捷指令自带明确意图，跳过页面上下文自动注入以避免重复
    handleSend?.(prompt, [], { skipPageContext: true })
  }

  return (
    <div className="h-full flex flex-col bg-background">
      {/* 顶栏 */}
      <header className="h-12 shrink-0 flex items-center gap-2 px-4 border-b border-border/40">
        <Brain className="h-4 w-4 text-scene shrink-0" aria-hidden />
        <h2 className="text-xs font-semibold tracking-widest uppercase text-foreground">
          AI 分析工作台
        </h2>
        <span className="text-[10px] text-muted-foreground font-mono ml-1">
          全宽对话 · 内联图表 · 操作闭环
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setSessionsOpen((v) => !v)}
            className={cn(
              'p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors',
              sessionsOpen && 'bg-scene/15 text-scene',
            )}
            aria-label="会话历史"
            title="会话历史"
          >
            <History className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              handleNewChat?.()
              setSessionsOpen(false)
            }}
            className="p-1.5 rounded-md text-muted-foreground hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors"
            aria-label="新建对话"
            title="新建对话"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {/* PROD-04b: 快捷指令栏（上下文感知，自动携带当前标的） */}
      <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-border/30 bg-secondary/20 overflow-x-auto custom-scrollbar">
        <Sparkles className="h-3.5 w-3.5 text-scene shrink-0" aria-hidden />
        {AI_QUICK_COMMANDS.map((cmd) => (
          <button
            key={cmd.key}
            type="button"
            onClick={() => runCommand(cmd)}
            className="shrink-0 flex items-center gap-1.5 rounded-full border border-scene/30 bg-scene/5 px-3 py-1 text-[11px] font-medium text-scene hover:bg-scene/15 hover:border-scene/50 scene-accent-transition transition-colors"
            title={cmd.ticker ? `${cmd.label}（自动带入当前标的）` : cmd.label}
          >
            <span aria-hidden>{cmd.emoji}</span>
            {cmd.label}
          </button>
        ))}
      </div>

      {/* 对话区 */}
      <div className="relative flex-1 min-h-0 flex flex-col max-w-4xl mx-auto w-full">
        {sessionsOpen && (
          <div className="absolute inset-0 z-20 flex bg-background/95 backdrop-blur-sm">
            <div className="h-full w-full overflow-hidden [&_aside]:w-full [&_aside]:border-r-0">
              <ChatSidebarWrapper />
            </div>
          </div>
        )}
        <MessageListArea />
        <ChatInputBox />
      </div>
    </div>
  )
}

export function FullscreenCopilot() {
  return (
    <ChatProvider>
      <FullscreenCopilotChrome />
    </ChatProvider>
  )
}
