'use client'

import React, { useCallback, useRef, useState } from 'react'
import { Brain, History, Plus, X, MessageSquare, Wallet } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { SCENE_META } from '@/features/scene/scene-mode-types'
import { useChatStore } from '@/stores/useChatStore'
import { useChat } from '@/features/copilot/useChat'
import { ChatSidebarWrapper } from '@/features/copilot/chat-sidebar-wrapper'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'

type CopilotTab = 'chat' | 'assets'

const DEFAULT_WIDTH = 520
const MIN_WIDTH = 360
const MAX_WIDTH = 800

function CopilotDrawerChrome({ width, onResizeStart }: { width: number; onResizeStart: (e: React.MouseEvent) => void }) {
  const closeCopilot = useLayoutStore((s) => s.closeCopilot)
  const handleNewChat = useChatStore((s) => s.handleNewChat)
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const [tab, setTab] = useState<CopilotTab>('chat')
  const context = useCopilotContextStore((s) => s.context)
  const clearContext = useCopilotContextStore((s) => s.clearContext)

  return (
    <div className="h-full flex flex-col bg-slate-50/90 dark:bg-zinc-950/95 backdrop-blur-md border-l border-white/10" style={{ width }}>
      {/* 左侧拖动条：拖动调整宽度，点击收起面板 */}
      <div
        onMouseDown={onResizeStart}
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize bg-transparent hover:bg-scene/40 active:bg-scene/60 transition-colors z-10"
        title="拖动调整宽度 · 点击收起"
      />
      <header className="shrink-0 border-b border-border/40">
        <div className="flex h-12 items-center gap-2 px-3">
          <Brain className="h-4 w-4 text-scene shrink-0" aria-hidden />
          <h2 className="text-xs font-semibold tracking-widest uppercase text-foreground truncate">
            AI Copilot
          </h2>
          <div className="ml-auto flex items-center gap-1">
            {tab === 'chat' && (
              <>
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
                  <Plus className="h- 3.5 w-3.5" />
                </button>
              </>
            )}
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
        </div>
        {/* Tab 切换：对话 / 资产 (COPILOT-06: 投研团队已迁至左导航 /research-team 宽屏页) */}
        <div className="flex items-center gap-1 px-3 pb-0 pt-1 border-b border-border/30">
          <TabButton active={tab === 'chat'} onClick={() => setTab('chat')} icon={<MessageSquare className="h-3.5 w-3.5" />} label="对话" />
          <TabButton active={tab === 'assets'} onClick={() => setTab('assets')} icon={<Wallet className="h-3.5 w-3.5" />} label="资产" />
        </div>
      </header>

      <div className="relative flex-1 min-h-0 flex flex-col">
        {tab === 'assets' ? (
          <CopilotAssetsPanel onClose={() => setTab('chat')} />
        ) : (
          <>
        {sessionsOpen && (
          <div className="absolute inset-0 z-20 flex bg-background/95 backdrop-blur-sm">
            <div className="h-full w-full overflow-hidden [&_aside]:w-full [&_aside]:border-r-0">
              <ChatSidebarWrapper />
            </div>
          </div>
        )}
        {context && (
          <div className="mx-3 mt-3 flex items-start gap-2 rounded-full border border-scene/30 bg-scene/10 px-3 py-2 text-xs text-scene scene-accent-transition">
            <Brain className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-medium text-scene">大脑上下文 · {context.title}</div>
              <div className="mt-0.5 whitespace-pre-wrap break-words text-scene/80">{context.summary}</div>
            </div>
            <button
              type="button"
              onClick={clearContext}
              className="ml-1 shrink-0 rounded p-0.5 text-scene/70 hover:bg-scene/20 hover:text-scene"
              aria-label="移除上下文"
              title="移除上下文"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        <MessageListArea />
        <ChatInputBox />
          </>
        )}
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'relative flex items-center gap-1.5 px-3 py-2 text-[12px] font-medium transition-colors border-b-2 -mb-px',
        active
          ? 'border-scene text-scene'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      {icon}
      {label}
    </button>
  )
}

// 💡 资产 Tab：组合快照占位（后续接入 Portfolio API）
function CopilotAssetsPanel({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 p-8 text-center text-muted-foreground">
      <div className="h-16 w-16 rounded-2xl bg-scene/10 border border-scene/20 flex items-center justify-center">
        <Wallet className="h-8 w-8 text-scene" />
      </div>
      <h3 className="text-sm font-semibold text-foreground">资产视图</h3>
      <p className="text-xs max-w-xs">实时组合净值、持仓分布与风险敞口将在此呈现。敬请期待投资组合 API 接入。</p>
      <button
        onClick={onClose}
        className="mt-2 rounded-full border border-border/50 px-3 py-1 text-xs hover:bg-secondary/50 transition-colors"
      >
        返回对话
      </button>
    </div>
  )
}

/**
 * 浮层覆盖式 AI Copilot 面板：fixed 定位，不挤压右侧主内容区宽度。
 * 支持拖动左侧边缘调整宽度，点击拖动条收起面板。
 * 折叠时 width→0，DOM/ChatProvider 不卸载，会话与 SSE 状态保留。
 */
export function GlobalCopilotDrawer() {
  const copilotOpen = useLayoutStore((s) => s.copilotOpen)
  const closeCopilot = useLayoutStore((s) => s.closeCopilot)
  const { handleClearAll } = useChat()
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const dragStartRef = useRef<{ x: number; width: number } | null>(null)
  const hasDraggedRef = useRef(false)

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragStartRef.current = { x: e.clientX, width }
    hasDraggedRef.current = false

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!dragStartRef.current) return
      const delta = dragStartRef.current.x - moveEvent.clientX
      if (Math.abs(delta) > 3) hasDraggedRef.current = true
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStartRef.current.width + delta))
      setWidth(newWidth)
    }

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      // 点击（未拖动）则收起面板
      if (!hasDraggedRef.current) {
        closeCopilot()
      }
      dragStartRef.current = null
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [width, closeCopilot])

  return (
    <aside
      data-testid="global-copilot-drawer"
      aria-hidden={!copilotOpen}
      className={cn(
        'fixed right-0 top-0 z-[51] h-full overflow-visible transition-[width] duration-300 ease-out',
        'shadow-2xl shadow-black/40',
        !copilotOpen && 'pointer-events-none',
      )}
      style={{ width: copilotOpen ? width : 0 }}
    >
      <CopilotDrawerChrome width={width} onResizeStart={handleResizeStart} />
    </aside>
  )
}

/** 右侧边缘把手：折叠时唤起副驾；PROD-04: 盯盘模式隐藏 */
export function CopilotEdgeHandle() {
  const copilotOpen = useLayoutStore((s) => s.copilotOpen)
  const settingsOpen = useLayoutStore((s) => s.settingsOpen)
  const toggleCopilot = useLayoutStore((s) => s.toggleCopilot)
  const sceneMode = useSceneModeStore((s) => s.mode)

  // PROD-04: 盯盘模式 AI 隐藏（右键唤起），不显示边缘把手
  if (SCENE_META[sceneMode].aiRole === 'hidden') return null
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
        'text-scene hover:bg-scene/15 hover:text-scene',
        'transition-colors shadow-lg',
      )}
      aria-label="展开 AI 副驾"
      title="AI 副驾 (Cmd+Shift+A)"
    >
      <Brain className="h-3.5 w-3.5" />
    </button>
  )
}
