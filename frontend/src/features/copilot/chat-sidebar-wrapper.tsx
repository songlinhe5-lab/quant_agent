import React from 'react'
import { SessionSidebar } from '@/features/copilot/session-sidebar'
import { useChatStore } from '@/stores/useChatStore'

export function ChatSidebarWrapper() {
  const sessionId = useChatStore((s) => s.sessionId)
  const handleSelectSession = useChatStore((s) => s.handleSelectSession)
  const handleNewChat = useChatStore((s) => s.handleNewChat)
  const setSidebarRef = useChatStore((s) => s.setSidebarRef)

  return (
    <SessionSidebar
      activeSessionId={sessionId}
      onSelectSession={handleSelectSession}
      onNewChat={handleNewChat}
      onRefReady={setSidebarRef}
    />
  )
}
