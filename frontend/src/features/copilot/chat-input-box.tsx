import React, { useState, useRef, useEffect, useContext } from 'react'
import { Send, Square, Trash2, Paperclip, X, Upload, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ChatMessagesContext, ChatActionContext } from './chat-context'
import { SUGGEST_STOCKS } from './shared'
import { ChatAttachment } from './types'

export function ChatInputBox() {
  const { isGenerating } = useContext(ChatMessagesContext)
  const { handleSend, handleStop, handleNewChat } = useContext(ChatActionContext)
  
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIndex, setMentionIndex] = useState<number>(0)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const newFiles = Array.from(e.target.files)
      Promise.all(newFiles.map(file => new Promise<ChatAttachment>((resolve) => {
        const reader = new FileReader()
        reader.onload = (ev) => resolve({ name: file.name, url: ev.target?.result as string, type: file.type })
        reader.readAsDataURL(file)
      }))).then(results => setAttachments(prev => [...prev, ...results]))
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    const files: File[] = []
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image/') !== -1 || items[i].type.indexOf('application/pdf') !== -1) {
        const file = items[i].getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length > 0) {
      Promise.all(files.map(file => new Promise<ChatAttachment>((resolve) => {
        const reader = new FileReader()
        reader.onload = (ev) => resolve({ name: file.name || `Pasted_${Date.now()}`, url: ev.target?.result as string, type: file.type })
        reader.readAsDataURL(file)
      }))).then(results => setAttachments(prev => [...prev, ...results]))
    }
  }
  
  // 💡 原生拖拽事件处理
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false)
    }
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const newFiles = Array.from(e.dataTransfer.files).filter(file => file.type.startsWith('image/') || file.type === 'application/pdf')
      if (newFiles.length > 0) {
        Promise.all(newFiles.map(file => new Promise<ChatAttachment>((resolve) => {
          const reader = new FileReader()
          reader.onload = (ev) => resolve({ name: file.name, url: ev.target?.result as string, type: file.type })
          reader.readAsDataURL(file)
        }))).then(results => setAttachments(prev => [...prev, ...results]))
      }
    }
  }

  const onSendClick = () => {
    if (input.trim() || attachments.length > 0) {
      handleSend(input, []) // 暂时禁用图片识别，不传递 attachments
      setInput('')
      setAttachments([])
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
        <div 
          className={cn(
            "p-4 border-t border-border/40 shrink-0 bg-slate-100/50 dark:bg-black/20 transition-all relative",
            isDragging && "bg-indigo-50/50 dark:bg-indigo-500/10"
          )}
          onDragOver={handleDragOver}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {/* 💡 拖拽时的毛玻璃提示蒙版 */}
          {isDragging && (
            <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm border-2 border-dashed border-indigo-500 m-2 rounded-xl pointer-events-none">
              <div className="flex flex-col items-center gap-2 text-indigo-500 dark:text-indigo-400">
                <Upload className="h-8 w-8 animate-bounce" />
                <span className="font-bold text-sm tracking-wide">松开鼠标，提取为投研附件</span>
              </div>
            </div>
          )}
          <div className="max-w-4xl mx-auto flex flex-col relative bg-white dark:bg-black/50 border border-slate-300 dark:border-white/10 rounded-xl p-2 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/50 transition-all shadow-sm">

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

            {/* 附件预览区 */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2 p-2 bg-slate-50/50 dark:bg-zinc-900/50 rounded-lg border border-border/20">
                {attachments.map((att, i) => (
                  <div key={i} className="relative flex items-center gap-2 bg-white dark:bg-black p-1.5 rounded-md border border-border/50 shadow-sm pr-7 group">
                    {att.type.startsWith('image/') ? (
                      <img src={att.url} alt={att.name} className="h-7 w-7 object-cover rounded" />
                    ) : (
                      <div className="h-7 w-7 flex items-center justify-center bg-indigo-500/10 rounded">
                        <FileText className="h-4 w-4 text-indigo-500" />
                      </div>
                    )}
                    <span className="text-[10px] max-w-[120px] truncate text-slate-700 dark:text-slate-300 font-medium">{att.name}</span>
                    <button 
                      onClick={() => setAttachments(prev => prev.filter((_, idx) => idx !== i))}
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="移除附件"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            
            <div className="flex items-end gap-2">
              <input 
                type="file" 
                multiple 
                accept="image/*,application/pdf"
                className="hidden" 
                ref={fileInputRef}
                onChange={handleFileChange}
              />
              
              <button 
                onClick={handleNewChat}
                className="h-10 w-10 shrink-0 rounded-lg hover:bg-red-500/10 text-muted-foreground hover:text-red-500 dark:hover:text-red-400 flex items-center justify-center transition-all mb-0.5" 
                title="清空上下文 (新推演)"
              >
                <Trash2 className="h-4 w-4" />
              </button>

              <button 
                onClick={() => fileInputRef.current?.click()}
                className="h-10 w-10 shrink-0 rounded-lg hover:bg-secondary/80 text-muted-foreground flex items-center justify-center transition-all mb-0.5" 
                title="上传图片或PDF附件"
              >
                <Paperclip className="h-4 w-4" />
              </button>
              
              <textarea 
                ref={textareaRef}
                value={input} 
                onChange={handleInputChange} 
                onKeyDown={handleKeyDown} 
                onPaste={handlePaste}
                placeholder="输入投研指令，或粘贴图片/PDF，例如：分析 AAPL 的近期新闻..." 
                className="w-full max-h-32 min-h-[44px] bg-transparent text-sm text-slate-900 dark:text-gray-200 placeholder:text-slate-400 dark:placeholder:text-gray-600 resize-none outline-none px-2 py-3 custom-scrollbar font-mono" 
                rows={1} 
              />
              
              {isGenerating ? (
                <button onClick={handleStop} className="h-10 w-10 shrink-0 rounded-lg bg-red-500 hover:bg-red-600 text-white flex items-center justify-center transition-all shadow-[0_0_10px_rgba(239,68,68,0.3)] mb-0.5 mr-0.5" title="停止生成">
                  <Square className="h-4 w-4 fill-current" />
                </button>
              ) : (
                <button onClick={onSendClick} disabled={!input.trim() && attachments.length === 0} className="h-10 w-10 shrink-0 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-[0_0_10px_rgba(var(--primary),0.3)] hover:shadow-[0_0_15px_rgba(var(--primary),0.5)] mb-0.5 mr-0.5" title="发送">
                  <Send className="h-4 w-4 ml-0.5" />
                </button>
              )}
            </div>
          </div>
          <div className="text-center mt-2">
            <span className="text-[10px] text-muted-foreground font-mono">Enter 换行 | Cmd/Ctrl + Enter 发送 | 支持粘贴图片/PDF</span>
          </div>
        </div>
  )
}