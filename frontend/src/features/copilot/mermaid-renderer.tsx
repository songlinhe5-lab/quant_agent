import React, { useEffect, useState } from 'react'
import mermaid from 'mermaid'
import { useTheme } from 'next-themes'
import { Sparkles, Loader2 } from 'lucide-react'

export function MermaidRenderer({ chart }: { chart: string }) {
  const { theme } = useTheme()
  const [svgHtml, setSvgHtml] = useState<string>('')
  const [error, setError] = useState(false)

  useEffect(() => {
    // 初始化 Mermaid 配置，并使其随系统的浅色/暗黑主题动态切换
    mermaid.initialize({
      startOnLoad: false,
      theme: theme === 'dark' ? 'dark' : 'default',
      fontFamily: 'monospace',
      securityLevel: 'loose'
    })
    
    const renderChart = async () => {
      try {
        setError(false)
        // 为每一个图表生成唯一的随机 ID，防止同一个页面多个 Mermaid 图表 ID 冲突
        const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`
        const { svg } = await mermaid.render(id, chart)
        setSvgHtml(svg)
      } catch (err) {
        console.error('Mermaid render error:', err)
        setError(true)
      }
    }
    
    if (chart) {
      renderChart()
    }
  }, [chart, theme])

  if (error) {
    return (
      <div className="my-4 p-3 rounded-lg border border-red-500/20 bg-red-500/10 text-xs text-red-400 font-mono shadow-sm">
        ⚠️ Mermaid 架构图解析失败，大模型生成的语法可能有误或不完整。
      </div>
    )
  }

  return (
    <div className="my-4 rounded-xl border border-border/40 bg-slate-50 dark:bg-zinc-950/50 p-2 shadow-lg overflow-hidden group">
      <div className="px-2 pt-2 pb-1 text-[10px] text-indigo-500/80 dark:text-indigo-400/80 font-bold uppercase tracking-widest flex items-center gap-1.5 border-b border-border/20 mb-2">
        <Sparkles className="w-3 h-3" /> 架构拓扑 (Mermaid Diagram)
      </div>
      <div className="p-2 overflow-x-auto custom-scrollbar flex justify-center min-h-[100px]">
        {svgHtml ? (
          <div dangerouslySetInnerHTML={{ __html: svgHtml }} />
        ) : (
          <div className="flex items-center gap-2 text-muted-foreground py-4 text-xs m-auto">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-500" /> 正在渲染拓扑图...
          </div>
        )}
      </div>
    </div>
  )
}