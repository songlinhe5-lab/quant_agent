import React, { useState, useRef, useEffect } from 'react'
import { Bot, Send, Loader2, Sparkles, RefreshCw, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useStrategyStore } from '../stores/useStrategyStore'
import { API_BASE_URL, getAccessToken, apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

export function AIChat() {
  const { messages, addMessage, updateMessage, setCode } = useStrategyStore()
  const [prompt, setPrompt] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [vibeExamples, setVibeExamples] = useState<string[]>([])
  const [isRefreshingVibe, setIsRefreshingVibe] = useState(false)
  const lastVibeFetchRef = useRef<number>(0)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { toast } = useToast()

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const fetchVibeExamples = async () => {
    const now = Date.now()
    if (now - lastVibeFetchRef.current < 1000 || isRefreshingVibe) return
    lastVibeFetchRef.current = now

    setIsRefreshingVibe(true)
    try {
      const res = await apiClient.get('/strategy/inspirations?limit=5')
      if (res.data?.status === 'success') {
        setVibeExamples(res.data.data)
      }
    } catch (e) {
      console.error('Failed to fetch vibe examples:', e)
    } finally {
      setTimeout(() => setIsRefreshingVibe(false), 800)
    }
  }

  useEffect(() => {
    if (messages.length === 0) {
      fetchVibeExamples()
    }
  }, [messages.length])

  const handleGenerate = async (overridePrompt?: string) => {
    const promptToUse = overridePrompt || prompt
    if (!promptToUse.trim() || isGenerating) return

    setIsGenerating(true)
    setPrompt('')
    
    const userMsgId = Date.now().toString()
    addMessage({ id: userMsgId, role: 'user', content: promptToUse })
    
    const assistantMsgId = (Date.now() + 1).toString()
    addMessage({ id: assistantMsgId, role: 'assistant', content: '', reasoning: '', status: 'typing' })
    
    try {
      const response = await fetch(`${API_BASE_URL}/strategy/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAccessToken() ? { 'Authorization': `Bearer ${getAccessToken()}` } : {})
        },
        body: JSON.stringify({ prompt: promptToUse })
      })

      if (!response.body) throw new Error('流式请求发起失败')
      
      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let done = false
      let accumulatedReasoning = ''
      let buffer = ''

      while (!done) {
        const { value, done: readerDone } = await reader.read()
        done = readerDone
        if (value) {
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (!line.trim()) continue
            try {
              const data = JSON.parse(line)
              if (data.status === 'reasoning' && data.data) {
                accumulatedReasoning += data.data
                const cleanReasoning = accumulatedReasoning.replace(/<\/?think>/gi, '').trimStart()
                updateMessage(assistantMsgId, { reasoning: cleanReasoning })
              } else if (data.status === 'success') {
                setCode(data.data)
                updateMessage(assistantMsgId, { content: '✨ 策略代码已生成并应用到主编辑器中，你可以进行审查或继续提出修改建议。', status: 'done' })
                toast({ title: '✨ 策略生成成功', description: '代码已就绪。' })
              } else if (data.status === 'error') {
                updateMessage(assistantMsgId, { content: `生成失败: ${data.message}`, status: 'error' })
              }
            } catch (e) { }
          }
        }
      }
      
      // Ensure status is marked as done
      const currentMsgs = useStrategyStore.getState().messages
      const lastMsg = currentMsgs.find(m => m.id === assistantMsgId)
      if (lastMsg && lastMsg.status === 'typing') {
          updateMessage(assistantMsgId, { status: 'done', content: '✨ 生成流已结束。' })
      }

    } catch (e: any) {
      updateMessage(assistantMsgId, { content: `网络异常: ${e.message}`, status: 'error' })
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-background relative">
      <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4 opacity-70 mt-10">
            <Bot className="h-12 w-12 text-primary opacity-50" />
            <div>
              <p className="text-sm font-semibold text-foreground">我是你的量化策略 AI 助理</p>
              <p className="text-xs text-muted-foreground mt-1">请描述你的策略逻辑，我会为你生成 Python 源码</p>
            </div>
            
            <div className="w-full max-w-sm mt-4 space-y-2 text-left">
              <div className="flex items-center justify-between px-1">
                <span className="text-[10px] text-muted-foreground font-medium flex items-center gap-1">
                  <Sparkles className="h-3 w-3" /> 灵感示例
                </span>
                <button 
                  onClick={fetchVibeExamples} 
                  disabled={isRefreshingVibe}
                  className="text-primary hover:text-primary/80 transition-colors"
                >
                  <RefreshCw className={cn("h-3 w-3", isRefreshingVibe && "animate-spin")} />
                </button>
              </div>
              {vibeExamples.map((ex, idx) => (
                <div 
                  key={idx} 
                  onClick={() => handleGenerate(ex)}
                  className="text-xs px-3 py-2 rounded-lg bg-secondary/30 hover:bg-primary/10 text-muted-foreground hover:text-primary border border-border/50 hover:border-primary/30 transition-all cursor-pointer leading-relaxed"
                >
                  {ex}
                </div>
              ))}
            </div>
          </div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className={cn("flex flex-col gap-1.5", msg.role === 'user' ? "items-end" : "items-start")}>
              <div className={cn(
                "flex items-center gap-1.5 text-[10px] font-semibold",
                msg.role === 'user' ? "text-primary flex-row-reverse" : "text-indigo-500"
              )}>
                {msg.role === 'user' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                <span>{msg.role === 'user' ? 'You' : 'Agent'}</span>
              </div>
              
              <div className={cn(
                "max-w-[90%] rounded-xl px-3 py-2 text-xs leading-relaxed",
                msg.role === 'user' 
                  ? "bg-primary text-primary-foreground rounded-tr-sm" 
                  : "bg-secondary/50 border border-border/50 rounded-tl-sm text-foreground"
              )}>
                {msg.role === 'assistant' && msg.reasoning && (
                  <div className="mb-2 pb-2 border-b border-border/50">
                    <div className="flex items-center gap-1.5 text-[10px] text-indigo-500/80 mb-1 font-mono">
                      <Sparkles className={cn("h-3 w-3", msg.status === 'typing' && "animate-pulse")} /> 
                      深度思考过程
                    </div>
                    <div className="text-muted-foreground font-mono text-[10px] whitespace-pre-wrap opacity-80">
                      {msg.reasoning}
                    </div>
                  </div>
                )}
                
                {msg.content ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : msg.status === 'typing' ? (
                  <div className="flex items-center gap-1 h-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/50 animate-bounce" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/50 animate-bounce delay-75" />
                    <span className="w-1.5 h-1.5 rounded-full bg-primary/50 animate-bounce delay-150" />
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t border-border/30 bg-secondary/10 shrink-0">
        <div className="relative group flex items-end gap-2 bg-background border border-border/60 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/30 rounded-xl p-1 transition-all">
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleGenerate()
              }
            }}
            placeholder="描述策略逻辑或要求修改代码 (Enter 发送)..."
            className="flex-1 max-h-32 min-h-[36px] bg-transparent outline-none text-xs resize-none p-2 custom-scrollbar"
            rows={1}
          />
          <Button
            size="icon"
            className="h-8 w-8 rounded-lg shrink-0 mb-0.5 mr-0.5"
            disabled={!prompt.trim() || isGenerating}
            onClick={() => handleGenerate()}
          >
            {isGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          </Button>
        </div>
        <div className="mt-2 text-center">
          <span className="text-[9px] text-muted-foreground">✨ AI 生成的代码将自动应用到左侧主编辑器中</span>
        </div>
      </div>
    </div>
  )
}