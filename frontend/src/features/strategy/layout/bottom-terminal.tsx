import { TerminalSquare, AlertCircle, Bot, Loader2 } from 'lucide-react'
import { useStrategyStore } from '../stores/useStrategyStore'
import { Button } from '@/components/ui/button'
import { useState } from 'react'
import { API_BASE_URL, getAccessToken } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

export function BottomTerminal() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const [isFixing, setIsFixing] = useState(false)

  const handleAutoFix = async () => {
    if (!store.runtimeError) return
    setIsFixing(true)
    
    try {
      const fixPrompt = `以下 Python 策略代码在沙箱执行/寻优时发生了运行时崩溃 (Runtime Error)：\n【报错信息】:\n${store.runtimeError}\n\n【错误源码】:\n${store.code}\n\n请仔细分析报错原因，直接修复该逻辑错误，并输出修复后的完整纯 Python 源码。严禁包含任何前言、后语或 Markdown 代码块标记。`
      
      const assistantMsgId = Date.now().toString()
      store.addMessage({ id: assistantMsgId, role: 'assistant', content: '', reasoning: '', status: 'reasoning' })
      
      const response = await fetch(`${API_BASE_URL}/strategy/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAccessToken() ? { 'Authorization': `Bearer ${getAccessToken()}` } : {})
        },
        body: JSON.stringify({ prompt: fixPrompt })
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
                store.updateMessage(assistantMsgId, { 
                  reasoning: accumulatedReasoning.replace(/<\/?think>/gi, '').trimStart(),
                  status: 'reasoning'
                })
              } else if (data.status === 'success') {
                store.setCode(data.data)
                store.setRuntimeError(null)
                store.updateMessage(assistantMsgId, { 
                  content: '✨ Agent 已经自动修复了运行时错误！代码已同步到主工作区，您可以再次尝试运行沙箱。',
                  status: 'done'
                })
                toast({ title: '🔧 AI 自动修复成功', description: '源码已更新。' })
              } else if (data.status === 'error') {
                store.updateMessage(assistantMsgId, { content: `❌ 修复失败: ${data.message}`, status: 'error' })
              }
            } catch (e) { }
          }
        }
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      setIsFixing(false)
    }
  }

  return (
    <div className="h-full flex flex-col bg-background relative">
      <div className="h-8 px-3 border-b border-border/30 bg-secondary/30 flex items-center shrink-0">
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
          <TerminalSquare className="h-3.5 w-3.5" /> 终端与执行日志
        </span>
      </div>
      <div className="flex-1 p-3 overflow-y-auto font-mono text-[11px] text-muted-foreground bg-[oklch(0.12_0.005_270)] dark:bg-[oklch(0.08_0.005_270)] custom-scrollbar">
        <p className="mb-1">➜ QuantEdge Strategy IDE Initialized.</p>
        <p className="text-emerald-500 mb-1">➜ Agent Connection: OK.</p>
        
        {store.runtimeError ? (
           <div className="mt-2 border border-red-500/30 bg-red-500/5 p-3 rounded-lg flex flex-col items-start gap-2 animate-in slide-in-from-bottom-2">
              <span className="text-red-500 font-bold flex items-center gap-1.5"><AlertCircle className="h-3.5 w-3.5"/> [Runtime Error] 沙箱执行崩溃</span>
              <span className="text-red-500/90 whitespace-pre-wrap">{store.runtimeError}</span>
              <Button onClick={handleAutoFix} disabled={isFixing} className="mt-1 h-7 px-3 text-[10px] bg-red-600 hover:bg-red-700 text-white shadow-sm gap-1.5">
                {isFixing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />}
                {isFixing ? '正在让 Agent 分析并修复...' : '✨ AI 分析与修复'}
              </Button>
           </div>
        ) : store.isSimulating ? (
           <p className="text-amber-500 opacity-80 mt-1 flex items-center gap-1.5"><Loader2 className="h-3 w-3 animate-spin" /> ➜ Sandbox simulation running...</p>
        ) : store.isOptimizing ? (
           <p className="text-indigo-500 opacity-80 mt-1 flex items-center gap-1.5"><Loader2 className="h-3 w-3 animate-spin" /> ➜ Grid searching optimal parameters...</p>
        ) : (
           <p className="text-amber-500 opacity-60 mt-1">➜ Waiting for sandbox execution...</p>
        )}
      </div>
    </div>
  )
}