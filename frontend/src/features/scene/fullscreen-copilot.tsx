'use client'

import React, { useContext, useState } from 'react'
import { Brain, History, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ChatProvider, ChatActionContext } from '@/features/copilot/chat-context'
import { ChatSidebarWrapper } from '@/features/copilot/chat-sidebar-wrapper'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'

/**
 * PROD-04: AI 分析模式全屏对话工作台
 * 复用 ChatProvider + MessageListArea + ChatInputBox，全宽布局。
 */
function FullscreenCopilotChrome() {
  const { handleNewChat } = useContext(ChatActionContext)
  const [sessionsOpen, setSessionsOpen] = useState(false)

  return (
    <div className="h-full flex flex-col bg-background">
      {/* 顶栏 */}
      <header className="h-12 shrink-0 flex items-center gap-2 px-4 border-b border-border/40">
        <Brain className="h-4 w-4 text-blue-400 shrink-0" aria-hidden />
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
              sessionsOpen && 'bg-primary/15 text-primary',
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
