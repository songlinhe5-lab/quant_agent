'use client'

import React, { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Loader2, Download, Save, Bot } from 'lucide-react'
import { useChatStore } from '@/stores/useChatStore'
import { useAssetLibrary } from '@/stores/useAssetLibrary'
import { toast } from '@/components/ui/use-toast'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'

/**
 * COPILOT-14: B2 对话模式（宽屏版）
 *  - 复用抽屉 MessageListArea + ChatInputBox（共享 useChatStore 单例，非新组件）
 *  - 消息流 760px 居中（MessageListArea wide）
 *  - 顶部工具条：ReAct · 第 n/8 步 + session_id 短码 + 导出按钮
 */
export function ChatWorkspace({ onStored }: { onStored?: () => void } = {}) {
  const messages = useChatStore((s) => s.messages)
  const isGenerating = useChatStore((s) => s.isGenerating)
  const sessionId = useChatStore((s) => s.sessionId)
  const handleExport = useChatStore((s) => s.handleExport)
  const addAsset = useAssetLibrary((s) => s.addAsset)

  // COPILOT-18: 对话导出升级为「同时存档」——生成 Markdown 并存入资产库

  // 当前 ReAct 步数：取最后一条生成中/最近的助手消息里的工具步数
  const currentStep = useMemo(() => {
    let step = 0
    if (isGenerating) {
      // 生成中：统计已有工具步数（running 或 done）
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i]
        if (m.role === 'assistant' && m.tools?.length) { step = m.tools.length; break }
      }
    } else {
      // 已完成：最后一条助手消息的工具数
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i]
        if (m.role === 'assistant' && m.tools?.length) { step = m.tools.length; break }
      }
    }
    return step
  }, [messages, isGenerating])

  const shortId = sessionId ? sessionId.slice(0, 8) : ''

  return (
    <div className="flex h-full flex-col">
      {/* 顶部工具条 */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border/20 px-3">
        <span className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground">
          <Bot className="h-3 w-3 text-violet-400" />
          ReAct · 第 {currentStep}/8 步
        </span>
        {shortId && (
          <span className="rounded border border-border/40 bg-secondary/30 px-1.5 py-px text-[9px] font-mono text-muted-foreground" title={`session_id: ${sessionId}`}>
            {shortId}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              const id = addAsset({
                type: 'chat',
                title: messages.find((m) => m.role === 'user')?.content?.slice(0, 20) || '对话',
                source: sessionId,
                content: messages.map((m) => `## ${m.role === 'user' ? '用户' : '助手'}\n\n${m.content}`).join('\n\n---\n\n'),
              })
              if (id) {
                toast({ title: '已存入资产库', description: '可在「资产库」面板查看' })
                onStored?.()
              } else {
                toast({ title: '已在资产库', description: '相同内容已存档，未重复添加' })
              }
            }}
            disabled={messages.length === 0}
            className="flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-[10px] text-sky-400 hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
            title="存入资产库"
          >
            <Save className="h-3 w-3" /> 存库
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={messages.length === 0}
            className="flex items-center gap-1 rounded-md border border-border/40 px-2 py-1 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
            title="导出当前会话为 Markdown"
          >
            <Download className="h-3 w-3" /> 导出
          </button>
        </div>
      </div>

      {/* 复用抽屉消息流（宽屏 760px 居中）+ 输入框 */}
      <div className="flex-1 min-h-0 flex flex-col">
        <MessageListArea wide />
        <ChatInputBox />
      </div>

      {/* 生成中提示（右下角步数浮标） */}
      {isGenerating && (
        <div className="pointer-events-none absolute bottom-24 right-6 z-10 flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-1 text-[10px] font-mono text-violet-300">
          <Loader2 className="h-3 w-3 animate-spin" /> ReAct · {currentStep}/8
        </div>
      )}
    </div>
  )
}
