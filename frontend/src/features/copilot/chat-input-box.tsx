import React, { useState, useRef, useEffect } from 'react'
import { Send, Square, Trash2, Brain, CandlestickChart, Shield, Filter, Star } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/stores/useChatStore'
import { useCopilotContextStore, type CopilotContextKind } from '@/stores/useCopilotContextStore'
import { SUGGEST_STOCKS } from './shared'

const CONTEXT_KIND_ICON: Record<CopilotContextKind, React.ReactNode> = {
  kline: <CandlestickChart className="h-3 w-3" />,
  risk: <Shield className="h-3 w-3" />,
  screener: <Filter className="h-3 w-3" />,
  analysis: <Star className="h-3 w-3" />,
}

export function ChatInputBox() {
  const isGenerating = useChatStore((s) => s.isGenerating)
  const handleSend = useChatStore((s) => s._sendImpl)
  const handleStop = useChatStore((s) => s.handleStop)
  const handleNewChat = useChatStore((s) => s.handleNewChat)
  const setInputSetterRef = useChatStore((s) => s.setInputSetterRef)
  const pageContext = useCopilotContextStore((s) => s.context)
  const clearContext = useCopilotContextStore((s) => s.clearContext)

  const [input, setInput] = useState('')
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIndex, setMentionIndex] = useState<number>(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 💡 注册 setInput 到 store ref，允许兄弟组件（MessageListArea）预填输入框
  useEffect(() => {
    setInputSetterRef((text: string) => {
      setInput(text)
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.focus()
          const placeholderIdx = text.indexOf('{输入标的}')
          if (placeholderIdx !== -1) {
            textareaRef.current.setSelectionRange(placeholderIdx, placeholderIdx + '{输入标的}'.length)
          }
        }
      }, 0)
    })
    return () => { setInputSetterRef(null) }
  }, [setInputSetterRef])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [input])

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setInput(val)
    const cursor = e.target.selectionStart
    const textBeforeCursor = val.substring(0, cursor)
    const match = textBeforeCursor.match(/(?:^|\s)@([a-zA-Z0-9.]*)$/)

    if (match) { setMentionQuery(match[1]); setMentionIndex(0) }
    else setMentionQuery(null)
  }

  const insertMention = (symbol: string) => {
    if (!textareaRef.current) return
    const cursor = textareaRef.current.selectionStart
    const textBeforeCursor = input.substring(0, cursor)
    const textAfterCursor = input.substring(cursor)
    const match = textBeforeCursor.match(/(^|\s)@([a-zA-Z0-9.]*)$/)
    if (match) {
      const prefix = textBeforeCursor.substring(0, match.index! + match[1].length)
      setInput(prefix + symbol + ' ' + textAfterCursor)
      setTimeout(() => {
        if (textareaRef.current) {
          const newCursor = prefix.length + symbol.length + 1
          textareaRef.current.setSelectionRange(newCursor, newCursor)
          textareaRef.current.focus()
        }
      }, 0)
    }
    setMentionQuery(null)
  }

  const onSendClick = () => {
    if (input.trim()) {
      handleSend?.(input)
      setInput('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing) return
    if (mentionQuery !== null) {
      const filtered = SUGGEST_STOCKS.filter(s => s.symbol.toLowerCase().includes(mentionQuery.toLowerCase()) || s.name.includes(mentionQuery))
      if (filtered.length > 0) {
        if (e.key === 'ArrowUp') { e.preventDefault(); setMentionIndex(prev => (prev > 0 ? prev - 1 : filtered.length - 1)); return }
        if (e.key === 'ArrowDown') { e.preventDefault(); setMentionIndex(prev => (prev < filtered.length - 1 ? prev + 1 : 0)); return }
        if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertMention(filtered[mentionIndex].symbol); return }
        if (e.key === 'Escape') { e.preventDefault(); setMentionQuery(null); return }
      }
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); onSendClick() }
  }

  return (
    <div className="p-4 border-t border-border/40 shrink-0 bg-slate-100/50 dark:bg-black/20 transition-all relative">
      {/* 💡 页面上下文 chip：有上下文时显示，可一键清除 */}
      {pageContext && (
        <div className="max-w-4xl mx-auto mb-2 flex items-center gap-2">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-scene/30 bg-scene/10 px-2.5 py-1 text-[10px] text-scene scene-accent-transition">
            {CONTEXT_KIND_ICON[pageContext.kind]}
            <span className="font-medium truncate max-w-[200px]">{pageContext.title}</span>
            <button
              type="button"
              onClick={clearContext}
              className="ml-0.5 rounded-full p-0.5 hover:bg-scene/20 transition-colors"
              title="移除页面上下文"
            >
              ×
            </button>
          </div>
        </div>
      )}

      <div className="max-w-4xl mx-auto flex flex-col relative bg-white dark:bg-black/50 border border-slate-300 dark:border-white/10 rounded-full p-1.5 focus-within:border-scene/50 focus-within:ring-1 focus-within:ring-scene/50 transition-all shadow-sm">

        {mentionQuery !== null && (
          <div className="absolute bottom-full left-12 mb-2 w-56 bg-white dark:bg-zinc-900 border border-border/50 rounded-xl shadow-xl overflow-hidden z-50 flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div className="px-3 py-1.5 text-[10px] font-bold text-muted-foreground bg-secondary/50 border-b border-border/30 uppercase tracking-widest">
              提及标的
            </div>
            <div className="max-h-48 overflow-y-auto custom-scrollbar p-1">
              {SUGGEST_STOCKS.filter(s => s.symbol.toLowerCase().includes(mentionQuery.toLowerCase()) || s.name.includes(mentionQuery)).map((s, i) => (
                <button
                  key={s.symbol}
                  className={cn("w-full text-left px-3 py-2 flex items-center justify-between text-xs rounded-lg transition-colors", i === mentionIndex ? "bg-primary/10 text-primary font-bold" : "hover:bg-secondary/50 text-foreground font-medium")}
                  onClick={() => insertMention(s.symbol)}
                >
                  <span className="font-mono">{s.symbol}</span>
                  <span className={cn("text-[10px]", i === mentionIndex ? "text-primary/70" : "text-muted-foreground")}>{s.name}</span>
                </button>
              ))}
              {SUGGEST_STOCKS.filter(s => s.symbol.toLowerCase().includes(mentionQuery.toLowerCase()) || s.name.includes(mentionQuery)).length === 0 && (
                <div className="px-3 py-3 text-xs text-muted-foreground text-center">无匹配标的</div>
              )}
            </div>
          </div>
        )}

        <div className="flex items-end gap-2">
          <button
            onClick={handleNewChat}
            className="h-10 w-10 shrink-0 rounded-full hover:bg-red-500/10 text-muted-foreground hover:text-red-500 dark:hover:text-red-400 flex items-center justify-center transition-all"
            title="清空上下文 (新推演)"
          >
            <Trash2 className="h-4 w-4" />
          </button>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="输入投研指令，例如：分析 AAPL 的近期新闻..."
            className="w-full max-h-32 min-h-[44px] bg-transparent text-sm text-slate-900 dark:text-gray-200 placeholder:text-slate-400 dark:placeholder:text-gray-600 resize-none outline-none px-2 py-3 custom-scrollbar"
            rows={1}
          />

          {isGenerating ? (
            <button onClick={handleStop} className="h-10 w-10 shrink-0 rounded-full bg-red-500 hover:bg-red-600 text-white flex items-center justify-center transition-all shadow-[0_0_10px_rgba(239,68,68,0.3)] mr-0.5" title="停止生成">
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button onClick={onSendClick} disabled={!input.trim()} className="h-10 w-10 shrink-0 rounded-full bg-scene hover:bg-[hsl(var(--scene-accent)/0.9)] text-white flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_0_10px_rgba(var(--scene-accent),0.3)] hover:shadow-[0_0_15px_rgba(var(--scene-accent),0.5)] mr-0.5" title="发送">
              <Send className="h-4 w-4 ml-0.5" />
            </button>
          )}
        </div>
      </div>
      <div className="text-center mt-2">
        <span className="text-[10px] text-muted-foreground">Enter 换行 | Cmd/Ctrl + Enter 发送 | @提及标的</span>
      </div>
    </div>
  )
}
