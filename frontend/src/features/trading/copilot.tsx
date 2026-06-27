"use client"

import React from 'react'
import { ChatProvider } from '@/features/copilot/chat-context'
import { ChatSidebarWrapper } from '@/features/copilot/chat-sidebar-wrapper'
import { ChatHeader } from '@/features/copilot/chat-header'
import { MessageListArea } from '@/features/copilot/message-list-area'
import { ChatInputBox } from '@/features/copilot/chat-input-box'

export function CopilotModule() {
  return (
    <ChatProvider>
      <div className="flex h-[calc(100vh-100px)] w-full overflow-hidden rounded-xl border border-border/40 shadow-2xl bg-slate-50/80 dark:bg-zinc-950/40 transition-colors">
        <ChatSidebarWrapper />
        <div className="flex-1 flex flex-col relative backdrop-blur-sm">
          <ChatHeader />
          <MessageListArea />
          <ChatInputBox />
        </div>
      </div>
    </ChatProvider>
  )
}