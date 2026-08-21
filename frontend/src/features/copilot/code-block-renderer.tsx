/**
 * COPILOT-11: 代码块渲染器
 * 语法高亮 + 折叠/展开 + 复制 + 策略跳转按钮。
 * 从 chat-message-item.tsx 拆出，原 80 行 JSX。
 */
import React, { useState, useEffect } from 'react'
import { ChevronDown, ChevronUp, Check, Copy, Code2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus, vs } from 'react-syntax-highlighter/dist/esm/styles/prism'

export const CodeBlockRenderer = React.memo(({
  codeContent, isStrategyCode, lang, isGenerating,
}: {
  codeContent: string
  isStrategyCode: boolean
  lang: string
  isGenerating: boolean
}) => {
  const [copied, setCopied] = useState(false)
  // 💡 初始加载时：代码 >50 行且非生成态（历史记录），默认折叠
  const [isCollapsed, setIsCollapsed] = useState(() => codeContent.split('\n').length > 50 && !isGenerating)
  const [prevGenerating, setPrevGenerating] = useState(isGenerating)
  const { theme } = useTheme()
  const navigate = useNavigate()

  // 💡 生成结束事件：AI 输出完毕且代码过长 → 自动折叠
  useEffect(() => {
    if (prevGenerating && !isGenerating && codeContent.split('\n').length > 50) {
      setIsCollapsed(true)
    }
    setPrevGenerating(isGenerating)
  }, [isGenerating, codeContent, prevGenerating])

  return (
    <div className="relative my-3 rounded-lg overflow-hidden border border-border/50 bg-slate-50 dark:bg-[#1e1e1e] shadow-sm">
      <div className="bg-secondary/40 text-muted-foreground text-[10px] px-3 py-1 font-mono border-b border-border/50 uppercase flex items-center justify-between">
        <span>{lang}</span>
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex items-center justify-center p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
          title={isCollapsed ? '展开代码' : '收起代码'}
        >
          {isCollapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
        </button>
      </div>

      {!isCollapsed && (
        <>
          <div className="overflow-x-auto custom-scrollbar text-[11px] leading-relaxed">
            <SyntaxHighlighter
              language={lang || 'text'}
              style={theme === 'dark' ? vscDarkPlus : vs}
              customStyle={{ margin: 0, padding: '12px', background: 'transparent' }}
              PreTag="div"
            >
              {String(codeContent).replace(/\n$/, '')}
            </SyntaxHighlighter>
          </div>
          <div className="flex items-center justify-end gap-2 bg-secondary/20 border-t border-border/40 px-2 py-1.5">
            <button
              onClick={() => {
                navigator.clipboard.writeText(codeContent)
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              }}
              className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors px-1.5 py-0.5 rounded hover:bg-secondary/60"
            >
              {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
              <span className={copied ? 'text-emerald-500' : ''}>{copied ? '已复制' : '复制代码'}</span>
            </button>
            {isStrategyCode && (
              <button
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sessionStorage.setItem('quant_strategy_initial_code', codeContent)
                  window.dispatchEvent(new CustomEvent('quant_strategy_code_invoke', { detail: { code: codeContent } }))
                  setTimeout(() => {
                    const tabTrigger = document.querySelector('[role="tab"][value="strategy"], [data-value="strategy"], a[href="/strategy"], a[href="#strategy"]') as HTMLElement
                    if (tabTrigger) tabTrigger.click()
                    else navigate('/strategy')
                  }, 50)
                }}
                className="flex items-center gap-1.5 hover:text-indigo-400 text-indigo-500 transition-colors bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 normal-case"
                title="将此代码发送至策略研发工作台（沙箱 · 未实盘）"
              >
                <Code2 className="h-3 w-3" />
                转为策略
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
})
