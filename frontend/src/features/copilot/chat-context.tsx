import React, { useState, useRef, useEffect, createContext, useCallback, useMemo } from 'react'
import { getAccessToken, apiClient, API_BASE_URL } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { useConfirmDialog } from '@/components/confirm-dialog'
import { SessionSidebarRef } from '@/features/copilot/session-sidebar'
import { ChatMessage, ToolStep, ChatAttachment } from './types'

export interface ChatState {
  messages: ChatMessage[];
  isGenerating: boolean;
  copiedIndex: number | null;
  quickPrompts: {title: string, prompt: string}[];
}

export const ChatSessionContext = createContext<string>('');
export const ChatMessagesContext = createContext<ChatState>({ messages: [], isGenerating: false, copiedIndex: null, quickPrompts: [] });
export const ChatActionContext = createContext<any>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string>('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isGenerating, setIsGenerating] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [quickPrompts, setQuickPrompts] = useState<{title: string, prompt: string}[]>([])
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()

  const sidebarRef = useRef<SessionSidebarRef>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  
  // 💡 Refs 防穿透：确保持久化的 Action 方法永远不会因为 state 变化而被重新声明
  const sessionIdRef = useRef(sessionId)
  const messagesRef = useRef(messages)
  const isGeneratingRef = useRef(isGenerating)

  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])
  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { isGeneratingRef.current = isGenerating }, [isGenerating])

  // 💡 异步获取随机灵感
  const refreshPrompts = useCallback(async () => {
    try {
      const res = await apiClient.get('/chat/suggestions?limit=6')
      if (res.data?.status === 'success' && res.data.data) {
        setQuickPrompts(res.data.data)
      }
    } catch (e) {
      setQuickPrompts([
        { title: '今日宏观风向', prompt: '提取今天全球核心经济体的宏观大事件，并给出你的风险判断。' },
        { title: '个股研报分析', prompt: '分析 0700.HK (腾讯控股) 最近的动态，结合基本面给出一份研报。' },
        { title: '生成交易策略', prompt: '请帮我用 Python 写一个双均线 (MA10, MA20) 交叉的实盘策略框架。' },
        { title: '技术面诊股', prompt: '帮我分析下 AAPL (苹果) 的最新走势。' }
      ])
    }
  }, [])

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setIsGenerating(false)
  }, [])

  const handleSelectSession = useCallback(async (id: string) => {
    handleStop() // 切换会话时，先打断正在生成的当前会话
    setSessionId(id)
    localStorage.setItem('quant_agent_active_session', id)
    setMessages([])
    
    try {
      // 💡 改用 apiClient，自动带上 Authorization Header，避免 401 报错
      const res = await apiClient.get(`/sessions/${id}`)
      if (res.data?.status === 'success' && res.data.data) {
        // 将后端完整的记忆（包含隐式的 tool 节点）解析转换为前端折叠 UI 需要的格式
        const displayMsgs: ChatMessage[] = []
        for (const m of res.data.data) {
          if (m.role === 'system') continue
          
          if (m.role === 'user') {
            displayMsgs.push({ role: 'user', content: m.content || '' })
          } else if (m.role === 'assistant') {
            // 💡 修复：合并连续的 assistant 消息，保证一次完整的 (思考+结论) 只占一个条目气泡
            const lastMsg = displayMsgs[displayMsgs.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
              if (m.content) {
                lastMsg.content = lastMsg.content ? lastMsg.content + '\n' + m.content : m.content;
              }
              if (m.tool_calls && Array.isArray(m.tool_calls)) {
                if (!lastMsg.tools) lastMsg.tools = [];
                m.tool_calls.forEach((tc: any) => {
                  lastMsg.tools!.push({ id: tc.id, name: tc.function?.name || 'unknown', input: tc.function?.arguments || '{}', status: 'done' })
                })
              }
            } else {
              const tools: ToolStep[] = []
              if (m.tool_calls && Array.isArray(m.tool_calls)) {
                m.tool_calls.forEach((tc: any) => {
                  tools.push({ id: tc.id, name: tc.function?.name || 'unknown', input: tc.function?.arguments || '{}', status: 'done' })
                })
              }
              displayMsgs.push({ role: 'assistant', content: m.content || '', tools: tools.length > 0 ? tools : [] })
            }
          } else if (m.role === 'tool') {
            // 💡 将后端的 tool 执行结果，精准挂载回上一条 assistant 消息对应的思考步骤中
            if (displayMsgs.length > 0) {
              const lastMsg = displayMsgs[displayMsgs.length - 1]
              if (lastMsg.role === 'assistant' && lastMsg.tools) {
                const targetTool = lastMsg.tools.find((t: ToolStep) => t.id === m.tool_call_id)
                if (targetTool) {
                  let resStr = typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2)
                  if (resStr.length > 1500) resStr = resStr.substring(0, 1500) + '\n\n... [数据过长，前端已自动截断以保持终端整洁] ...'
                  targetTool.result = resStr
                }
              }
            }
          }
        }
        setMessages(displayMsgs)
      }
    } catch (error) {
      console.error('获取会话记录失败:', error)
    }
  }, [handleStop])

  const handleNewChat = useCallback(() => {
    handleStop() // 新建会话时也打断正在生成的进程
    const newId = crypto.randomUUID()
    setSessionId(newId)
    localStorage.setItem('quant_agent_active_session', newId)
    setMessages([])
    refreshPrompts() // 💡 每次创建新会话都重新洗牌给新灵感
  }, [handleStop, refreshPrompts])

  const handleCopy = useCallback((text: string, idx: number) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(idx)
    setTimeout(() => setCopiedIndex(null), 2000)
  }, [])

  const handleClearAll = useCallback(async () => {
    const ok = await confirm({ title: '清空所有聊天记录', description: '此操作将永久删除云端所有历史会话，无法恢复。', confirmLabel: '全部清空' })
    if (!ok) return;
    try {
      const res = await apiClient.delete('/sessions')
      if (res.data?.status === 'success') {
        toast({ title: '清理成功', description: '所有聊天记录已彻底清空' })
        sidebarRef.current?.fetchSessions()
        handleNewChat()
      }
    } catch (error) {
      console.error('清空记录失败:', error)
      toast({ title: '清理失败', description: '无法连接到服务器完成清理', variant: 'destructive' })
    }
  }, [handleNewChat, toast])

  const handleExport = useCallback(() => {
    const currentMessages = messagesRef.current
    if (currentMessages.length === 0) return
    const content = currentMessages.map(m => {
      let text = `### [${m.role.toUpperCase()}]\n${m.content}`;
      if (m.tools && m.tools.length > 0) {
        text += '\n\n**[思考过程与工具调用]**\n' + m.tools.map(t => `- 运行工具: ${t.name}\n  输入: ${t.input}\n  结果: ${t.result || '已完成'}`).join('\n\n')
      }
      return text;
    }).join('\n\n---\n\n');
    
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `QuantEdge_Copilot_${new Date().toISOString().slice(0,10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [])

  // --- 核心流式请求逻辑 (SSE / NDJSON) ---
  const handleSend = useCallback(async (text: string, sendAttachments: ChatAttachment[] = []) => {
    if (isGeneratingRef.current) return

    const finalContent = text.trim()
    if (!finalContent && sendAttachments.length === 0) return

    const userMsg: ChatMessage = { 
      role: 'user', 
      content: finalContent,
      attachments: sendAttachments.length > 0 ? [...sendAttachments] : undefined
    }
    
    setMessages(prev => [...prev, userMsg])
    setIsGenerating(true)

    const currentAssistantMsg: ChatMessage = { role: 'assistant', content: '', tools: [], startTime: Date.now() }

    try {
      abortControllerRef.current = new AbortController()
      setMessages(prev => [...prev, currentAssistantMsg])

      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getAccessToken()}`
        },
        body: JSON.stringify({
          messages: [userMsg],
          session_id: sessionIdRef.current
        }),
        credentials: 'include',
        signal: abortControllerRef.current.signal
      })

      if (!res.body) throw new Error('网络响应异常 (No Body)')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()

      // 💡 渲染节流：限制高频 Markdown 解析频率，每 50ms 更新一次 UI (约 20 FPS)
      let lastUpdateTime = Date.now()
      let buffer = '' // 用于拼接跨 Chunk 被截断的文本流

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // 将新解码的字符串追加到 buffer
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        
        // 最后一行可能是不完整的 JSON 字符串，将其留到下一次处理
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const data = JSON.parse(line)
            
            // 根据大模型吐出的数据格式，精细化组装 Markdown 内容
            if (data.type === 'text_chunk') {
              currentAssistantMsg.content += data.content
              if (!currentAssistantMsg.thinkEndTime && currentAssistantMsg.content.includes('</think>')) {
                currentAssistantMsg.thinkEndTime = Date.now()
              }
            } else if (data.type === 'tool_start') {
              // 推入一个新的思考折叠块
              currentAssistantMsg.tools = [
                ...(currentAssistantMsg.tools || []),
                { name: data.name, input: data.input, status: 'running' }
              ]
            } else if (data.type === 'tool_result') {
              // 将当前正在执行的思考块标记为已完成，并附上执行结果
              if (currentAssistantMsg.tools && currentAssistantMsg.tools.length > 0) {
                const tools = [...currentAssistantMsg.tools]
                // 倒序查找对应名称且正在 running 的 tool，确保并发调用的回执能够精准挂载
                let targetIdx = tools.length - 1
                for (let i = tools.length - 1; i >= 0; i--) {
                  if (tools[i].name === data.name && tools[i].status === 'running') { targetIdx = i; break; }
                }
                const targetTool = tools[targetIdx]
                let resStr = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2)
                
                // 💡 前端自适应安全截断：往回寻找换行符或完整的大括号，防止切破 JSON/Markdown 结构引发 React 解析报错
                if (resStr.length > 1500) {
                  let cutIdx = 1500;
                  for (const sep of ['\n', '}', ']', '.', '。', ' ']) {
                    const idx = resStr.lastIndexOf(sep, 1500);
                    if (idx > 1000) { cutIdx = idx + sep.length; break; }
                  }
                  resStr = resStr.substring(0, cutIdx) + `\n\n... [数据过长，前端已自适应截断隐藏了 ${resStr.length - cutIdx} 个字符以保持终端整洁] ...`
                }
                
                tools[targetIdx] = { ...targetTool, status: 'done', result: resStr }
                currentAssistantMsg.tools = tools
              }
            } else if (data.type === 'error') {
              currentAssistantMsg.content += data.content
            }

            // 💡 触发 React 重新渲染：仅在关键事件 (Tool) 或距离上次渲染超过 50ms 时触发
            const now = Date.now()
            const isToolEvent = data.type === 'tool_start' || data.type === 'tool_result' || data.type === 'error'
            
            if (isToolEvent || now - lastUpdateTime > 50) {
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = { ...currentAssistantMsg }
                return updated
              })
              lastUpdateTime = now
            }
          } catch (e) {
            // 忽略非法的 JSON 切片
          }
        }
      }
      
      // 消息完全接收完毕后，触发左侧边栏刷新以更新【最新标题】和【消息数】
      sidebarRef.current?.fetchSessions()

    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('生成已由用户主动终止')
        currentAssistantMsg.content += '\n\n> 🛑 **思考已中断**: 用户主动终止了当前的推演。'
        return
      }
      console.error('流式请求异常:', error)
      currentAssistantMsg.content += '\n\n> ❌ **网络/打断异常**: 无法连接到大模型后端网关或请求被意外中断。'
    } finally {
      setIsGenerating(false)
      abortControllerRef.current = null
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last && last.role === 'assistant') {
          // 💡 兜底强制刷入：确保流结束时，被节流拦截的最后一段尾部文本成功上屏
          last.content = currentAssistantMsg.content
          // 💡 清理战场：若存在因强行打断而僵死在 running 状态的工具，强制将其结束防止 UI 无限转圈
          last.tools = currentAssistantMsg.tools?.map(t => t.status === 'running' ? { ...t, status: 'done', result: '🛑 工具调用已被强制打断。' } : t)
          if (last.startTime && !last.thinkEndTime) {
            last.thinkEndTime = Date.now()
          }
        }
        return updated
      })
    }
  }, [])

  const handleRetry = useCallback((idx: number) => {
    if (isGeneratingRef.current) return
    setMessages(prev => {
      let prevUserMsg = ''
      for (let i = idx - 1; i >= 0; i--) {
        if (prev[i].role === 'user') {
          prevUserMsg = prev[i].content
          break
        }
      }
      if (prevUserMsg) {
        setTimeout(() => handleSend(prevUserMsg), 0)
      }
      return prev
    })
  }, [handleSend])

  // 💡 初始化钩子：从 LocalStorage 恢复上一次的未完成会话 (确保在 handleSend 声明之后)
  useEffect(() => {
    const savedSessionId = localStorage.getItem('quant_agent_active_session')
    if (savedSessionId) {
      handleSelectSession(savedSessionId) // 直接向后端请求拉取历史数据
    } else {
      handleNewChat()
    }
    refreshPrompts()
    
    // 💡 跨模块联动：接收来自其他模块 (如 Screener) 的自动查询指令
    const initialPrompt = sessionStorage.getItem('quant_copilot_initial_prompt')
    if (initialPrompt) {
      sessionStorage.removeItem('quant_copilot_initial_prompt')
      // 留出时间让左侧边栏列表和会话状态就绪
      setTimeout(() => {
        handleSend(initialPrompt, [])
      }, 800)
    }
    
    // 💡 支持 SPA 单页应用内的无刷新跨模块调用 (接收选股器等模块发来的提问指令)
    const handleCrossModulePrompt = (e: Event) => {
      const customEvent = e as CustomEvent<{ prompt: string }>
      if (customEvent.detail?.prompt) {
        handleSend(customEvent.detail.prompt, [])
      }
    }
    window.addEventListener('quant_copilot_invoke', handleCrossModulePrompt)
    return () => window.removeEventListener('quant_copilot_invoke', handleCrossModulePrompt)
  }, [handleSelectSession, handleNewChat, refreshPrompts, handleSend])

  // 💡 极致的 Action Context 引用固化，永远不需要刷新
  const actions = useMemo(() => ({
    handleSelectSession, handleNewChat, handleStop, handleCopy, handleRetry, handleSend, handleClearAll, handleExport, sidebarRef, refreshPrompts
  }), [handleSelectSession, handleNewChat, handleStop, handleCopy, handleRetry, handleSend, handleClearAll, handleExport, refreshPrompts])

  const messageState = useMemo(() => ({ messages, isGenerating, copiedIndex, quickPrompts }), [messages, isGenerating, copiedIndex, quickPrompts])

  return (
    <ChatSessionContext.Provider value={sessionId}>
      <ChatMessagesContext.Provider value={messageState}>
        <ChatActionContext.Provider value={actions}>
          {children}
        </ChatActionContext.Provider>
      </ChatMessagesContext.Provider>
    </ChatSessionContext.Provider>
  )
}