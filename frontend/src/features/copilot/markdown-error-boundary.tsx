/**
 * COPILOT-11: Markdown 渲染错误边界
 * 拦截 ReactMarkdown 因残缺语法树导致的渲染崩溃，降级显示纯文本。
 * 流式恢复：新 Chunk 到达后自动重试渲染。
 */
import React from 'react'
import { AlertTriangle } from 'lucide-react'

export class MarkdownErrorBoundary extends React.Component<
  { children: React.ReactNode; fallbackContent: string },
  { hasError: boolean; error: any }
> {
  constructor(props: any) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: any) {
    return { hasError: true, error }
  }

  componentDidCatch(error: any, errorInfo: any) {
    console.error('Markdown 渲染崩溃拦截:', error, errorInfo)
  }

  componentDidUpdate(prevProps: any) {
    // 💡 流式恢复：新 Chunk 到达可能修复残缺语法树，重置错误状态重试渲染
    if (this.state.hasError && prevProps.fallbackContent !== this.props.fallbackContent) {
      this.setState({ hasError: false, error: null })
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-500/90 text-[11px] font-mono whitespace-pre-wrap break-words shadow-inner">
          <div className="font-bold mb-2 flex items-center gap-1.5 text-red-500">
            <AlertTriangle className="h-3.5 w-3.5" /> 渲染异常降级保护 (Render Fallback)
          </div>
          {this.props.fallbackContent}
        </div>
      )
    }
    return this.props.children
  }
}
