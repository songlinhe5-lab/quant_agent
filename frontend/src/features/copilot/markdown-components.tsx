/**
 * COPILOT-11: ReactMarkdown 自定义组件配置工厂
 * 返回 components 对象供 ReactMarkdown 使用。
 * 从 chat-message-item.tsx 拆出，含代码块路由 (echarts/mermaid/chart-annotations/python)。
 */
import React from 'react'
import { Sparkles, Loader2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { EChartsRenderer } from '@/features/copilot/echarts-renderer'
import { MermaidRenderer } from '@/features/copilot/mermaid-renderer'
import { CodeBlockRenderer } from './code-block-renderer'

export function useMarkdownComponents({ onSend, isGenerating }: { onSend: (text: string) => void; isGenerating: boolean }) {
  const navigate = useNavigate()

  return React.useMemo(() => ({
    p: ({ ...props }: any) => <div className="mb-2 last:mb-0 leading-relaxed" {...props} />,
    a: ({ ...props }: any) => <a className="text-emerald-500 hover:text-emerald-400 hover:underline underline-offset-4" target="_blank" rel="noreferrer" {...props} />,
    h1: ({ ...props }: any) => <h1 className="text-lg font-bold mt-4 mb-2 text-foreground" {...props} />,
    h2: ({ ...props }: any) => <h2 className="text-base font-bold mt-3 mb-2 text-foreground" {...props} />,
    h3: ({ ...props }: any) => <h3 className="text-sm font-bold mt-2 mb-1 text-foreground" {...props} />,
    ul: ({ ...props }: any) => <ul className="list-disc list-outside ml-4 mb-2 space-y-1" {...props} />,
    ol: ({ ...props }: any) => <ol className="list-decimal list-outside ml-4 mb-2 space-y-1" {...props} />,
    li: ({ children, ...props }: any) => {
      const extractText = (nodes: any): string => {
        let text = ''
        React.Children.forEach(nodes, child => {
          if (typeof child === 'string') text += child
          else if (React.isValidElement(child) && (child.props as any).children) text += extractText((child.props as any).children)
        })
        return text
      }
      const fullText = extractText(children).trim()
      const match = fullText.match(/^["“「](.+?)["”」]$/)
      if (match) {
        const cmd = match[1]
        return (
          <li className="list-none inline-block mr-2 mt-1 mb-1 -ml-4">
            <button onClick={() => onSend(cmd)} disabled={isGenerating} className="px-3 py-1.5 rounded-full bg-indigo-500/10 text-indigo-400 text-xs border border-indigo-500/20 hover:bg-indigo-500/20 hover:text-indigo-300 hover:shadow-[0_0_10px_rgba(99,102,241,0.2)] transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed" title="点击快捷发送">
              <Sparkles className="w-3 h-3" /> {cmd}
            </button>
          </li>
        )
      }
      return <li className="pl-1" {...props}>{children}</li>
    },
    blockquote: ({ ...props }: any) => <blockquote className="border-l-2 border-primary/50 pl-3 py-1.5 my-2 bg-primary/5 text-muted-foreground italic rounded-r-md" {...props} />,
    code: ({ inline, className, children, ...props }: any) => {
      const match = /language-(\w+)/.exec(className || '')
      const lang = match ? match[1].toLowerCase() : ''
      const codeContent = String(children)
      const isInline = typeof inline === 'boolean' ? inline : !match && !codeContent.includes('\n')
      const isStrategyCode = (lang === 'python' || !match) && (
        codeContent.includes('def ') || codeContent.includes('class ') ||
        codeContent.includes('import ') || codeContent.includes('pd.') || codeContent.includes('np.')
      ) && codeContent.split('\n').length > 3

      if (!isInline && lang === 'echarts') {
        try {
          const jsonObj = JSON.parse(String(children))
          return (
            <div className="my-4 rounded-xl border border-border/40 bg-zinc-950/50 p-2 shadow-lg overflow-hidden">
              <div className="px-2 pt-2 pb-1 text-[10px] text-emerald-400/80 font-bold uppercase tracking-widest flex items-center gap-1.5 border-b border-border/20 mb-2">
                <Sparkles className="w-3 h-3" /> 数据可视化研判 (Data Visualization)
              </div>
              <EChartsRenderer options={jsonObj} />
            </div>
          )
        } catch (_err) {
          if (isGenerating) {
            return (
              <div className="my-4 p-3 rounded-lg border border-border/30 bg-zinc-950/30 text-xs text-muted-foreground font-mono flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                动态图表解析中，等待 JSON 格式闭环...
              </div>
            )
          }
          return (
            <details className="my-4 rounded-lg border border-red-500/20 bg-red-500/10 text-xs">
              <summary className="px-3 py-2 text-red-400 font-mono cursor-pointer select-none">⚠️ 图表 JSON 解析失败（已截断或损坏）</summary>
              <pre className="px-3 pb-3 pt-1 text-red-400/80 font-mono whitespace-pre-wrap break-all">{String(children)}</pre>
            </details>
          )
        }
      }
      if (!isInline && lang === 'mermaid') return <MermaidRenderer chart={String(children)} />
      // 💡 PROD-02: chart-annotations 块由 SSE 事件推送至 useChartAnnotationStore 渲染
      if (!isInline && lang === 'chart-annotations') return null

      return !isInline ? (
        <CodeBlockRenderer codeContent={codeContent} isStrategyCode={isStrategyCode} lang={match ? match[1] : 'code'} isGenerating={isGenerating} />
      ) : (
        <code className="bg-secondary/60 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded text-[11px] font-mono mx-0.5" {...props}>{children}</code>
      )
    },
    table: ({ ...props }: any) => <div className="overflow-x-auto my-3 custom-scrollbar rounded-lg border border-border/40 bg-slate-50 dark:bg-secondary/10 shadow-sm"><table className="w-full text-left border-collapse text-xs" {...props} /></div>,
    thead: ({ ...props }: any) => <thead className="bg-slate-100 dark:bg-secondary/40 border-b border-border/40" {...props} />,
    tr: ({ ...props }: any) => <tr className="hover:bg-slate-200/50 dark:hover:bg-secondary/30 transition-colors group" {...props} />,
    th: ({ ...props }: any) => <th className="px-3 py-2 font-semibold text-foreground whitespace-nowrap border-b border-border/20" {...props} />,
    td: ({ ...props }: any) => <td className="px-3 py-2 border-b border-border/10 text-muted-foreground group-hover:text-foreground transition-colors" {...props} />,
    hr: ({ ...props }: any) => <hr className="my-4 border-border/30" {...props} />,
  }), [onSend, isGenerating, navigate])
}
