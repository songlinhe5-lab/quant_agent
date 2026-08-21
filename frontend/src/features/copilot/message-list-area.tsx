import React, { useRef, useEffect } from 'react'
import { Sparkles, RefreshCw } from 'lucide-react'
import { useChatStore } from '@/stores/useChatStore'
import { STOCK_QUICK_COMMANDS } from './chat-context'
import { ChatMessageItem } from './chat-message-item'
import { getIconForTitle } from './shared'

export function MessageListArea() {
  const messages = useChatStore((s) => s.messages)
  const isGenerating = useChatStore((s) => s.isGenerating)
  const copiedIndex = useChatStore((s) => s.copiedIndex)
  const quickPrompts = useChatStore((s) => s.quickPrompts)
  const handleCopy = useChatStore((s) => s.handleCopy)
  const handleRetry = useChatStore((s) => s.handleRetry)
  const handleSend = useChatStore((s) => s._sendImpl)
  const refreshPrompts = useChatStore((s) => s.refreshPrompts)
  const inputSetterRef = useChatStore((s) => s.inputSetterRef)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const userScrolledUpRef = useRef(false)

  useEffect(() => {
    // 💡 修复滚动陷阱：生成期间使用 instant(auto) 瞬间跳跃保持底部对齐，防止平滑动画多重触发导致的页面剧烈跳动和视差粘滞
    // 💡 增加用户滚动打断机制：如果用户手动向上滚动了，则暂停自动滚动到底部
    if (!userScrolledUpRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: isGenerating ? 'auto' : 'smooth' })
    }
  }, [messages, isGenerating])

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget;
    // 容差 100px 以内认为是在最底部
    const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
    userScrolledUpRef.current = !isAtBottom;
  }

  return (
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar" onScroll={handleScroll}>
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground space-y-6 animate-in fade-in duration-700 max-w-2xl mx-auto px-4">
              <div className="flex flex-col items-center gap-3">
                <div className="h-16 w-16 rounded-2xl bg-scene/10 border border-scene/20 flex items-center justify-center shadow-[0_0_15px_rgba(var(--scene-accent),0.2)]">
                  <Sparkles className="h-8 w-8 text-scene" />
                </div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-bold text-foreground tracking-widest uppercase">Hermes Quant Agent</h3>
                  <button onClick={refreshPrompts} className="p-1 rounded-md hover:bg-secondary/80 text-muted-foreground hover:text-foreground transition-colors" title="换一批灵感"><RefreshCw className="h-3.5 w-3.5" /></button>
                </div>
                <p className="text-xs">量化投研主脑已就绪，请输入投研指令或选择下方快捷模板...</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 w-full mt-4">
                {quickPrompts.slice(0, 6).map((qp, i) => (
                  <button key={i} onClick={() => handleSend?.(qp.prompt)} className="flex items-start gap-3 p-3 rounded-xl border border-border/40 bg-secondary/20 hover:bg-secondary/60 hover:border-scene/40 transition-all text-left group shadow-sm hover:shadow-md">
                    <div className="p-2 rounded-lg bg-background border border-border/50 group-hover:shadow-sm group-hover:border-scene/30">
                      {getIconForTitle(qp.title)}
                    </div>
                    <div className="min-w-0">
                      <h4 className="text-xs font-bold text-foreground mb-1 truncate">{qp.title}</h4>
                      <p className="text-[10px] text-muted-foreground line-clamp-2">{qp.prompt}</p>
                    </div>
                  </button>
                ))}
              </div>

              {/* 个股深度研判快捷指令 */}
              <div className="w-full mt-4">
                <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-3 text-center">
                  个股深度研判 · 快捷指令
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {STOCK_QUICK_COMMANDS.map((cmd) => (
                    <button
                      key={cmd.label}
                      onClick={() => inputSetterRef?.(cmd.template)}
                      className="flex items-center gap-3 bg-scene/10 border border-scene/20 rounded-lg p-3 hover:bg-scene/20 cursor-pointer transition-colors text-left group"
                    >
                      <span className="text-lg shrink-0">{cmd.emoji}</span>
                      <div className="min-w-0">
                        <h5 className="text-sm font-semibold text-foreground group-hover:text-scene transition-colors truncate">{cmd.label}</h5>
                        <p className="text-[10px] text-muted-foreground line-clamp-1 mt-0.5">{cmd.template}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <ChatMessageItem key={idx} msg={msg} idx={idx} isLast={idx === messages.length - 1} isGenerating={isGenerating} copiedIndex={copiedIndex} onCopy={handleCopy} onRetry={handleRetry} onSend={(text) => handleSend?.(text)} />
            ))
          )}
          <div ref={messagesEndRef} />
        </div>
  )
}
