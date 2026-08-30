import { useEffect, useRef, useCallback } from 'react'
import { useToast } from '@/hooks/use-toast'
import { useConfirmDialog } from '@/components/confirm-dialog-context'
import { apiClient, clearTokens, emitAuthRequired } from '@/lib/api-client'
import { useChatStore, injectSendImpl } from '@/stores/useChatStore'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'
import { useChartAnnotationStore } from '@/stores/useChartAnnotationStore'
import { runChatStream, classifyChatError, isNewResearchTask } from '@/features/copilot/chat-stream-service'
import type { ChatMessage } from '@/features/copilot/types'

/**
 * COPILOT-01: 薄编排 Hook——替代原 480 行 ChatProvider。
 * 状态由 useChatStore (Zustand) 持有，SSE 解析由 chat-stream-service 独立处理，
 * 本 Hook 仅负责：初始化生命周期 / handleSend 编排 / toast·confirm 副作用。
 */
export function useChat() {
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()
  const abortRef = useRef<AbortController | null>(null)

  const store = useChatStore

  /** 统一从 store 读取 sidebarRef（由 ChatSidebarWrapper → SessionSidebar 的 onRefReady 写入） */
  const getSidebar = () => store.getState().sidebarRef

  // ─── handleSend：核心 SSE 编排 ───
  const handleSend = useCallback(async (text: string, opts?: { skipPageContext?: boolean }) => {
    const s = store.getState()
    if (s.isGenerating) return
    let finalContent = text.trim()
    if (!finalContent) return

    // RESEARCH-01: 新投研任务自动开新会话（会话隔离）
    // 同一会话内再次发起"深度研判/投研"视为独立新任务：先开新会话，
    // 避免上次标的历史（工具结果/中间分析）污染本次研判。
    // 仅对用户手动输入生效；跨模块自动查询（skipPageContext）不静默切会话。
    if (!opts?.skipPageContext && s.messages.length > 0 && isNewResearchTask(finalContent)) {
      store.getState().handleNewChat()
      toast({ title: '已开启新投研会话', description: '为避免上次调研内容干扰，本次深度研判在独立会话中进行' })
    }
    const current = store.getState()

    // PROD-01: 会话首条消息自动注入当前页面上下文
    if (!opts?.skipPageContext && current.messages.length === 0) {
      const ctx = useCopilotContextStore.getState().context
      if (ctx?.summary) {
        finalContent = `[当前页面上下文 · ${ctx.title}]\n${ctx.summary}\n[/上下文]\n\n${finalContent}`
      }
    }

    const userMsg: ChatMessage = { role: 'user', content: finalContent }
    store.setState(prev => ({ messages: [...prev.messages, userMsg] }))
    store.getState().setIsGenerating(true)

    const assistantMsg: ChatMessage = { role: 'assistant', content: '', tools: [], startTime: Date.now() }
    store.setState(prev => ({ messages: [...prev.messages, assistantMsg] }))

    try {
      abortRef.current = new AbortController()

      await runChatStream(
        { sessionId: current.sessionId, userContent: finalContent, signal: abortRef.current.signal },
        {
          onTextChunk: (content) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') last.content += content
          },
          // COPILOT-03/P0-4: 消费后端 reasoning_chunk 真实推理流（Plan 阶段）
          onReasoningChunk: (content) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') last.reasoning = (last.reasoning || '') + content
          },
          onThinkEnd: () => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant' && !last.thinkEndTime) {
              last.thinkEndTime = Date.now()
            }
          },
          onToolStart: (name, input) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') {
              last.tools = [...(last.tools || []), { name, input, status: 'running' }]
            }
          },
          onToolResult: (name, result) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last?.tools) {
              const tools = [...last.tools]
              let targetIdx = tools.length - 1
              for (let i = tools.length - 1; i >= 0; i--) {
                if (tools[i].name === name && tools[i].status === 'running') { targetIdx = i; break }
              }
              // COPILOT-21: 检测工具失败（result 为 {status:'error'} 或含 error 标记）
              let isError = false
              let errorMsg: string | undefined
              if (typeof result === 'object' && result !== null) {
                const r = result as Record<string, unknown>
                if (r.status === 'error' || r.error || r.failed) {
                  isError = true
                  errorMsg = (r.message as string) || (r.error as string) || (r.detail as string) || '工具执行失败'
                }
              } else if (typeof result === 'string' && /error|failed|exception/i.test(result) && result.length < 300) {
                isError = true
                errorMsg = result
              }
              let resStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
              // 💡 前端自适应安全截断
              if (resStr.length > 1500) {
                let cutIdx = 1500
                for (const sep of ['\n', '}', ']', '.', '。', ' ']) {
                  const idx = resStr.lastIndexOf(sep, 1500)
                  if (idx > 1000) { cutIdx = idx + sep.length; break }
                }
                resStr = resStr.substring(0, cutIdx) + `\n\n... [数据过长，前端已自适应截断隐藏了 ${resStr.length - cutIdx} 个字符以保持终端整洁] ...`
              }
              tools[targetIdx] = {
                ...tools[targetIdx],
                status: isError ? 'error' : 'done',
                result: resStr,
                timestamp: Date.now(),
                errorMessage: isError ? errorMsg : undefined,
              }
              last.tools = tools
            }
          },
          onError: (content) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') last.content += content
          },
          onStrategyCode: (code) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') {
              if (!last.strategyBlocks) last.strategyBlocks = []
              last.strategyBlocks.push({ code })
            }
          },
          onChartAnnotation: (data) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') {
              if (!last.chartAnnotations) last.chartAnnotations = []
              last.chartAnnotations.push(data)
              const symbol = data.symbol || useCopilotContextStore.getState().context?.symbol
              if (symbol) useChartAnnotationStore.getState().setAnnotation(symbol, data)
            }
          },
          onIterationLimitReached: (maxIterations) => {
            const msgs = store.getState().messages
            const last = msgs[msgs.length - 1]
            if (last && last.role === 'assistant') {
              last.iterationLimitReached = true
            }
          },
          onFlush: () => {
            // 触发 React 重新渲染：浅拷贝最后一条 assistant 消息
            store.setState(prev => {
              const updated = [...prev.messages]
              const lastIdx = updated.length - 1
              if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                updated[lastIdx] = { ...updated[lastIdx] }
              }
              return { messages: updated }
            })
          },
          onStreamEnd: () => {
            getSidebar()?.fetchSessions()
          },
        },
      )
    } catch (error: any) {
      const { message, isAuth } = classifyChatError(error)
      const msgs = store.getState().messages
      const last = msgs[msgs.length - 1]
      if (last && last.role === 'assistant') last.content += message
      if (isAuth) {
        clearTokens()
        emitAuthRequired()
      }
    } finally {
      store.setState(prev => {
        const updated = [...prev.messages]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant') {
          last.tools = last.tools?.map(t => t.status === 'running' ? { ...t, status: 'done', result: '🛑 工具调用已被强制打断。' } : t)
          if (last.startTime && !last.thinkEndTime) last.thinkEndTime = Date.now()
        }
        return { isGenerating: false, messages: updated }
      })
      abortRef.current = null
    }
  }, [])

  // 💡 注入 send 实现到 store，供 handleRetry 等调用
  useEffect(() => {
    injectSendImpl(handleSend)
    return () => injectSendImpl(null)
  }, [handleSend])

  // ─── handleClearAll：需要 toast + confirm ───
  const handleClearAll = useCallback(async () => {
    const ok = await confirm({
      title: '清空所有聊天记录',
      description: '此操作将永久删除云端所有历史会话，无法恢复。',
      confirmLabel: '全部清空',
    })
    if (!ok) return
    try {
      const res = await apiClient.delete('/sessions')
      if (res.data?.status === 'success') {
        toast({ title: '清理成功', description: '所有聊天记录已彻底清空' })
        getSidebar()?.fetchSessions()
        store.getState().handleNewChat()
      }
    } catch (error) {
      console.error('清空记录失败:', error)
      toast({ title: '清理失败', description: '无法连接到服务器完成清理', variant: 'destructive' })
    }
  }, [toast, confirm])

  // ─── 初始化生命周期 ───
  useEffect(() => {
    const s = store.getState()
    const savedSessionId = localStorage.getItem('quant_agent_active_session')
    if (savedSessionId) {
      s.handleSelectSession(savedSessionId)
    } else {
      s.handleNewChat()
    }
    s.refreshPrompts()

    // 💡 跨模块联动：接收来自其他模块的自动查询指令
    const initialPrompt = sessionStorage.getItem('quant_copilot_initial_prompt')
    if (initialPrompt) {
      sessionStorage.removeItem('quant_copilot_initial_prompt')
      setTimeout(() => handleSend(initialPrompt, { skipPageContext: true }), 800)
    }

    const handleCrossModulePrompt = (e: Event) => {
      const customEvent = e as CustomEvent<{ prompt: string }>
      if (customEvent.detail?.prompt) {
        handleSend(customEvent.detail.prompt, { skipPageContext: true })
      }
    }
    window.addEventListener('quant_copilot_invoke', handleCrossModulePrompt)
    return () => window.removeEventListener('quant_copilot_invoke', handleCrossModulePrompt)
  }, [])

  return { handleClearAll, handleSend }
}
