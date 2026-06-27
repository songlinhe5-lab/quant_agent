import React, { useContext } from 'react'
import { SessionSidebar } from '@/features/copilot/session-sidebar'
import { ChatSessionContext, ChatActionContext } from './chat-context'

export function ChatSidebarWrapper() {
  const sessionId = useContext(ChatSessionContext)
  const { handleSelectSession, handleNewChat, sidebarRef } = useContext(ChatActionContext)

  return (
    <SessionSidebar 
      ref={sidebarRef}
      activeSessionId={sessionId}
      onSelectSession={handleSelectSession}
      onNewChat={handleNewChat}
    />
  )
}