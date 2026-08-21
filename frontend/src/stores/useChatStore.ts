import { create } from 'zustand'
import { apiClient } from '@/lib/api-client'
import type { ChatMessage, ToolStep, StrategyBlock } from '@/features/copilot/types'

// 💡 从 assistant 消息内容中提取策略代码块（用于历史记录恢复）
function extractStrategyBlocks(content: string): StrategyBlock[] {
  const blocks: StrategyBlock[] = []
  const pattern = /```python\s*\n([\s\S]*?)```/g
  let match
  while ((match = pattern.exec(content)) !== null) {
    const code = match[1].trim()
    if (code && /backtest|deploy|Backtest|Deploy/.test(code)) {
      blocks.push({ code })
    }
  }
  return blocks
}

export interface ChatState {
  sessionId: string
  messages: ChatMessage[]
  isGenerating: boolean
  copiedIndex: number | null
  quickPrompts: { title: string; prompt: string }[]
  sidebarRef: { fetchSessions: () => Promise<void> } | null
  inputSetterRef: ((text: string) => void) | null
}

export interface ChatActions {
  setSessionId: (id: string) => void
  setMessages: (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => void
  setIsGenerating: (v: boolean) => void
  setCopiedIndex: (idx: number | null) => void
  setQuickPrompts: (prompts: { title: string; prompt: string }[]) => void
  setSidebarRef: (ref: { fetchSessions: () => Promise<void> } | null) => void
  setInputSetterRef: (fn: ((text: string) => void) | null) => void
  handleCopy: (text: string, idx: number) => void
  handleStop: () => void
  handleExport: () => void
  handleSelectSession: (id: string) => Promise<void>
  handleNewChat: () => void
  handleRetry: (idx: number) => void
  refreshPrompts: () => Promise<void>
  /** 由 useChat hook 注入，编排 SSE 流式请求 */
  _sendImpl: ((text: string, opts?: { skipPageContext?: boolean }) => Promise<void>) | null
}

export interface ChatStore extends ChatState, ChatActions {}

export const useChatStore = create<ChatStore>()((set, get) => ({
  // --- State ---
  sessionId: '',
  messages: [],
  isGenerating: false,
  copiedIndex: null,
  quickPrompts: [],
  sidebarRef: null,
  inputSetterRef: null,
  _sendImpl: null,

  // --- Simple setters ---
  setSessionId: (id) => set({ sessionId: id }),
  setMessages: (updater) => set((s) => ({
    messages: typeof updater === 'function' ? updater(s.messages) : updater,
  })),
  setIsGenerating: (v) => set({ isGenerating: v }),
  setCopiedIndex: (idx) => set({ copiedIndex: idx }),
  setQuickPrompts: (prompts) => set({ quickPrompts: prompts }),
  setSidebarRef: (ref) => set({ sidebarRef: ref }),
  setInputSetterRef: (fn) => set({ inputSetterRef: fn }),

  // --- Actions ---
  handleCopy: (text, idx) => {
    navigator.clipboard.writeText(text)
    set({ copiedIndex: idx })
    setTimeout(() => set({ copiedIndex: null }), 2000)
  },

  handleStop: () => {
    // abort 由 _sendImpl 注入的 controller 处理，这里只重置 UI 状态
    set({ isGenerating: false })
  },

  handleExport: () => {
    const { messages } = get()
    if (messages.length === 0) return
    const content = messages.map(m => {
      let text = `### [${m.role.toUpperCase()}]\n${m.content}`
      if (m.tools && m.tools.length > 0) {
        text += '\n\n**[思考过程与工具调用]**\n' + m.tools.map(t => `- 运行工具: ${t.name}\n  输入: ${t.input}\n  结果: ${t.result || '已完成'}`).join('\n\n')
      }
      return text
    }).join('\n\n---\n\n')
    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `QuantEdge_Copilot_${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  },

  handleSelectSession: async (id) => {
    const state = get()
    state.handleStop()
    set({ sessionId: id, messages: [] })
    localStorage.setItem('quant_agent_active_session', id)

    try {
      const res = await apiClient.get(`/sessions/${id}`)
      if (res.data?.status === 'success' && res.data.data) {
        const displayMsgs: ChatMessage[] = []
        for (const m of res.data.data) {
          if (m.role === 'system') continue
          if (m.role === 'user') {
            displayMsgs.push({ role: 'user', content: m.content || '' })
          } else if (m.role === 'assistant') {
            const lastMsg = displayMsgs[displayMsgs.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
              if (m.content) {
                lastMsg.content = lastMsg.content ? lastMsg.content + '\n' + m.content : m.content
              }
              if (m.tool_calls && Array.isArray(m.tool_calls)) {
                if (!lastMsg.tools) lastMsg.tools = []
                m.tool_calls.forEach((tc: any) => {
                  lastMsg.tools!.push({ id: tc.id, name: tc.function?.name || 'unknown', input: tc.function?.arguments || '{}', status: 'done' })
                })
              }
              lastMsg.strategyBlocks = extractStrategyBlocks(lastMsg.content)
            } else {
              const tools: ToolStep[] = []
              if (m.tool_calls && Array.isArray(m.tool_calls)) {
                m.tool_calls.forEach((tc: any) => {
                  tools.push({ id: tc.id, name: tc.function?.name || 'unknown', input: tc.function?.arguments || '{}', status: 'done' })
                })
              }
              displayMsgs.push({
                role: 'assistant', content: m.content || '',
                tools: tools.length > 0 ? tools : [],
                strategyBlocks: extractStrategyBlocks(m.content || ''),
              })
            }
          } else if (m.role === 'tool') {
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
        set({ messages: displayMsgs })
      }
    } catch (error) {
      console.error('获取会话记录失败:', error)
    }
  },

  handleNewChat: () => {
    get().handleStop()
    const newId = crypto.randomUUID()
    set({ sessionId: newId, messages: [] })
    localStorage.setItem('quant_agent_active_session', newId)
    get().refreshPrompts()
  },

  handleRetry: (idx) => {
    const { messages, _sendImpl } = get()
    if (get().isGenerating || !_sendImpl) return
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        setTimeout(() => _sendImpl(messages[i].content), 0)
        break
      }
    }
  },

  refreshPrompts: async () => {
    try {
      const res = await apiClient.get('/chat/suggestions?limit=6')
      if (res.data?.status === 'success' && res.data.data) {
        set({ quickPrompts: res.data.data })
      }
    } catch (_e) {
      set({
        quickPrompts: [
          { title: '今日宏观风向', prompt: '提取今天全球核心经济体的宏观大事件，并给出你的风险判断。' },
          { title: '个股研报分析', prompt: '分析 0700.HK (腾讯控股) 最近的动态，结合基本面给出一份研报。' },
          { title: '生成交易策略', prompt: '请帮我用 Python 写一个双均线 (MA10, MA20) 交叉的实盘策略框架。' },
          { title: '技术面诊股', prompt: '帮我分析下 AAPL (苹果) 的最新走势。' },
        ],
      })
    }
  },
}))

// 💡 供 useChat hook 注入 SSE 编排实现，避免 store 直接依赖 React hooks
export function injectSendImpl(fn: ChatStore['_sendImpl']) {
  useChatStore.setState({ _sendImpl: fn })
}

/** 快捷获取 handleSend（hook 注入后可用） */
export function getChatSend() {
  return useChatStore.getState()._sendImpl
}
