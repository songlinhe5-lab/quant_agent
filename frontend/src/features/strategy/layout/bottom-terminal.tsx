import { TerminalSquare, AlertCircle, Bot, Loader2, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { useStrategyStore } from '../stores'
import { Button } from '@/components/ui/button'
import { useState } from 'react'
import { API_BASE_URL, fetchWithAuth } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

/**
 * BottomTerminal — 运行日志抽屉 (可折叠, 级别分色, 折叠态摘要)。
 * STRAT-07: 删除硬编码装饰开场白; 首行即真实事件; 失败时抽屉头部挂错误卡 + 重试。
 */
export function BottomTerminal() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const [isOpen, setIsOpen] = useState(true)
  const [isFixing, setIsFixing] = useState(false)

  const isRunning = store.isSimulating || store.isOptimizing

  const handleAutoFix = async () => {
    if (!store.runtimeError) return
    setIsFixing(true)
    try {
      const fixPrompt = `以下 Python 策略代码在沙箱执行/寻优时发生了运行时崩溃 (Runtime Error)：\n【报错信息】:\n${store.runtimeError}\n\n【错误源码】:\n${store.code}\n\n请仔细分析报错原因，直接修复该逻辑错误，并输出修复后的完整纯 Python 源码。严禁包含任何前言、后语或 Markdown 代码块标记。`

      const assistantMsgId = Date.now().toString()
      store.addMessage({ id: assistantMsgId, role: 'assistant', content: '', reasoning: '', status: 'reasoning' })

      const response = await fetchWithAuth(`${API_BASE_URL}/strategy/generate`, {
        method: 'POST',
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
                store.enterDiff(data.data, 'auto-fix')
                store.setRuntimeError(null)
                store.updateMessage(assistantMsgId, {
                  content: '✨ Agent 已经自动修复了运行时错误！请在 Diff 编辑器中审查并确认变更。',
                  status: 'done'
                })
                toast({ title: '🔧 AI 自动修复成功', description: '请在 Diff 视图中审查修复。' })
              } else if (data.status === 'error') {
                store.updateMessage(assistantMsgId, { content: `❌ 修复失败: ${data.message}`, status: 'error' })
              }
            } catch (_e) { /* ignore */ }
          }
        }
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally {
      setIsFixing(false)
    }
  }

  // 折叠态摘要: 首行即真实事件, 不再硬编码装饰开场白
  const summary = store.runtimeError
    ? `运行失败: ${store.runtimeError.split('\n')[0].slice(0, 60)}`
    : isRunning
      ? `${store.isOptimizing ? '寻优' : '运行'}中 · ${store.sandboxProgress || store.optimizeProgress || 0}%${store.sandboxStage ? ` · ${store.sandboxStage}` : ''}`
      : '空闲'

  const logLines: Array<{ level: 'info' | 'warn' | 'error'; text: string }> = []
  if (store.runtimeError) {
    logLines.push({ level: 'error', text: store.runtimeError })
  }
  if (isRunning) {
    const stage = store.sandboxStage || (store.isOptimizing ? store.optimizeStage : '') || ''
    logLines.push({
      level: 'info',
      text: `${store.isOptimizing ? '参数寻优' : '沙箱回测'}进行中 · ${store.sandboxProgress || store.optimizeProgress || 0}%${stage ? ` · ${stage}` : ''}`,
    })
  }
  if (logLines.length === 0) {
    logLines.push({ level: 'info', text: '空闲 · 点击"▶ 运行沙箱"开始推演' })
  }

  const levelCls: Record<string, string> = {
    info: 'text-muted-foreground',
    warn: 'text-amber-500',
    error: 'text-red-500',
  }
  const levelTag: Record<string, string> = {
    info: 'INFO',
    warn: 'WARNING',
    error: 'ERROR',
  }

  return (
    <div className="h-full flex flex-col bg-background relative overflow-hidden">
      {/* 抽屉头部 */}
      <div className="h-9 px-3 border-b border-border/30 bg-secondary/30 flex items-center gap-2 shrink-0">
        <button onClick={() => setIsOpen(v => !v)} className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors">
          {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <TerminalSquare className="h-3.5 w-3.5" /> 运行日志
        </button>
        {isRunning && (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
            <Loader2 className="h-2.5 w-2.5 animate-spin" /> 运行中
          </span>
        )}
        {store.runtimeError && (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-red-500/15 text-red-500">失败</span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground truncate">{summary}</span>
        {isRunning && (
          <Button size="sm" variant="ghost" onClick={() => { store.setSimulating(false); store.setOptimizing(false) }} className="h-6 px-2 text-[10px] text-muted-foreground hover:text-red-500 shrink-0 gap-1">
            停止
          </Button>
        )}
        {store.runtimeError && !isFixing && (
          <Button size="sm" variant="ghost" onClick={() => setIsOpen(true)} className="h-6 px-2 text-[10px] text-muted-foreground hover:text-foreground shrink-0 gap-1">
            <RefreshCw className="h-3 w-3" /> 重试
          </Button>
        )}
      </div>

      {/* 折叠内容: 日志级别分色 */}
      {isOpen && (
        <div className="flex-1 min-h-0 overflow-y-auto p-3 font-mono text-[11px] bg-[oklch(0.12_0.005_270)] dark:bg-[oklch(0.08_0.005_270)] custom-scrollbar space-y-1.5">
          {logLines.map((line, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className={cn("w-[60px] flex-none font-bold", levelCls[line.level])}>{levelTag[line.level]}</span>
              <span className={cn("break-all whitespace-pre-wrap", levelCls[line.level])}>{line.text}</span>
            </div>
          ))}

          {/* 失败时抽屉头部下方挂错误卡 */}
          {store.runtimeError && (
            <div className="mt-2 border border-red-500/30 bg-red-500/5 p-3 rounded-lg flex flex-col items-start gap-2 animate-in slide-in-from-bottom-2">
              <span className="text-red-500 font-bold flex items-center gap-1.5"><AlertCircle className="h-3.5 w-3.5" /> [Runtime Error] 沙箱执行崩溃</span>
              <span className="text-red-500/90 whitespace-pre-wrap break-all">{store.runtimeError}</span>
              <Button onClick={handleAutoFix} disabled={isFixing} className="mt-1 h-7 px-3 text-[10px] bg-red-600 hover:bg-red-700 text-white shadow-sm gap-1.5">
                {isFixing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />}
                {isFixing ? '正在让 Agent 分析并修复...' : '✨ AI 分析与修复'}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
