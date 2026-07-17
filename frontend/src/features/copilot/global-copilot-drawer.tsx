'use client'

import React, { useContext, useState } from 'react'
import { Brain, History, Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { ChatProvider, ChatActionContext } from '@/features/copilot/chat-context'
import { ChatSidebarWrapper } from '@/features/copilot/chat-sidebar-wrapper'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'

const DRAWER_WIDTH = 480

function CopilotDrawerChrome() {
  const closeCopilot = useLayoutStore((s) => s.closeCopilot)
  const { handleNewChat } = useContext(ChatActionContext)
  const [sessionsOpen, setSessionsOpen] = useState(false)

  return (
    <div
      className="h-full flex flex-col bg-slate-50/90 dark:bg-zinc-950/95 backdrop-blur-md border-l border-white/10"
      style={{ width: DRAWER_WIDTH }}
    >
      <header className="h-12 shrink-0 flex items-center gap-2 px-3 border-b border-border/40">
        <Brain className="h-4 w-4 text-violet-400 shrink-0" aria-hidden />
        <h2 className="text-xs font-semibold tracking-widest uppercase text-foreground truncate">
          AI Copilot
        </h2>
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
          <button
            type="button"
            onClick={closeCopilot}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            aria-label="关闭 AI 副驾"
            title="关闭 (Cmd+Shift+A)"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      <div className="relative flex-1 min-h-0 flex flex-col">
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

/**
 * 浮层覆盖式 AI Copilot 面板：fixed 定位，不挤压右侧主内容区宽度。
 * 折叠时 width→0，DOM/ChatProvider 不卸载，会话与 SSE 状态保留。
 */
export function GlobalCopilotDrawer() {
  const copilotOpen = useLayoutStore((s) => s.copilotOpen)

  return (
    <aside
      data-testid="global-copilot-drawer"
      aria-hidden={!copilotOpen}
      className={cn(
        'fixed right-0 top-0 z-30 h-full overflow-hidden transition-[width] duration-300 ease-out',
        'border-l border-border/40 shadow-2xl shadow-black/40',
        !copilotOpen && 'pointer-events-none',
      )}
      style={{ width: copilotOpen ? DRAWER_WIDTH : 0 }}
    >
      <ChatProvider>
        <CopilotDrawerChrome />
      </ChatProvider>
    </aside>
  )
}

/** 右侧边缘把手：折叠时唤起副驾 */
export function CopilotEdgeHandle() {
  const copilotOpen = useLayoutStore((s) => s.copilotOpen)
  const settingsOpen = useLayoutStore((s) => s.settingsOpen)
  const toggleCopilot = useLayoutStore((s) => s.toggleCopilot)

  if (copilotOpen || settingsOpen) return null

  return (
    <button
      type="button"
      data-testid="copilot-edge-handle"
      onClick={toggleCopilot}
      className={cn(
        'fixed right-0 top-1/2 z-40 -translate-y-1/2',
        'flex h-24 w-5 items-center justify-center rounded-l-md',
        'border border-r-0 border-white/10 bg-zinc-950/80 backdrop-blur-md',
        'text-violet-400 hover:bg-violet-500/15 hover:text-violet-300',
        'transition-colors shadow-lg',
      )}
      aria-label="展开 AI 副驾"
      title="AI 副驾 (Cmd+Shift+A)"
    >
      <Brain className="h-3.5 w-3.5" />
    </button>
  )
}
