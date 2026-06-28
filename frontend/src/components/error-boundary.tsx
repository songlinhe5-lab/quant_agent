/**
 * 三级 Error Boundary 系统
 * FE-04: Module 级 / Panel 级 / Chart 级错误隔离
 */

import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import logger from '@/lib/logger'

// ─── 错误边界 Props ────────────────────────────────────────────────
interface ErrorBoundaryProps {
  children: ReactNode
  level: 'module' | 'panel' | 'chart'
  name: string
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

// ─── 基础 Error Boundary ────────────────────────────────────────────
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo })
    
    // 根据级别使用不同的日志方法
    const message = `[ErrorBoundary:${this.props.level}] ${this.props.name} 崩溃`
    const context = {
      level: this.props.level,
      name: this.props.name,
      error: {
        name: error.name,
        message: error.message,
        stack: error.stack,
      },
      componentStack: errorInfo.componentStack,
    }

    if (this.props.level === 'module') {
      logger.error(message, error, context)
    } else {
      logger.warn(message, context)
    }
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      // 自定义 fallback
      if (this.props.fallback) {
        return this.props.fallback
      }

      // 默认 fallback UI
      return <ErrorFallback
        level={this.props.level}
        name={this.props.name}
        error={this.state.error}
        onReset={this.handleReset}
      />
    }

    return this.props.children
  }
}

// ─── 错误降级 UI ────────────────────────────────────────────────────
interface ErrorFallbackProps {
  level: 'module' | 'panel' | 'chart'
  name: string
  error: Error | null
  onReset: () => void
}

function ErrorFallback({ level, name, error, onReset }: ErrorFallbackProps) {
  const isChart = level === 'chart'
  const isPanel = level === 'panel'

  // Chart 级别：最小化显示
  if (isChart) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[100px] p-4 bg-destructive/5 rounded-lg border border-destructive/20">
        <AlertTriangle className="h-5 w-5 text-destructive/60 mb-2" aria-hidden="true" />
        <p className="text-xs text-muted-foreground text-center">
          图表渲染失败
        </p>
        <Button variant="ghost" size="sm" className="mt-2 h-6 text-xs" onClick={onReset}>
          <RefreshCw className="h-3 w-3 mr-1" />
          重试
        </Button>
      </div>
    )
  }

  // Panel 级别：中等大小
  if (isPanel) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-6 bg-destructive/5 rounded-lg border border-destructive/20">
        <AlertTriangle className="h-8 w-8 text-destructive/60 mb-3" aria-hidden="true" />
        <h3 className="text-sm font-medium text-foreground mb-1">{name} 面板异常</h3>
        <p className="text-xs text-muted-foreground text-center max-w-xs mb-4">
          {error?.message || '渲染过程中发生未知错误'}
        </p>
        <Button variant="outline" size="sm" onClick={onReset}>
          <RefreshCw className="h-3 w-3 mr-1" />
          重新加载
        </Button>
      </div>
    )
  }

  // Module 级别：完整显示
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[300px] p-8 bg-destructive/5 rounded-lg border border-destructive/20">
      <AlertTriangle className="h-12 w-12 text-destructive/60 mb-4" aria-hidden="true" />
      <h2 className="text-lg font-semibold text-foreground mb-2">{name} 模块崩溃</h2>
      <p className="text-sm text-muted-foreground text-center max-w-md mb-2">
        该模块遇到意外错误，已自动上报日志。
      </p>
      {error && (
        <pre className="text-xs text-destructive/80 bg-background/50 rounded p-3 mb-4 max-w-md overflow-auto">
          {error.message}
        </pre>
      )}
      <div className="flex gap-2">
        <Button variant="outline" onClick={onReset}>
          <RefreshCw className="h-4 w-4 mr-2" />
          重新加载模块
        </Button>
        <Button variant="ghost" onClick={() => window.location.reload()}>
          刷新页面
        </Button>
      </div>
    </div>
  )
}

// ─── 快捷组件 ───────────────────────────────────────────────────────

/**
 * Module 级 Error Boundary
 * 用于包裹整个功能模块（如 QuotesModule、ScreenerModule）
 */
export function ModuleErrorBoundary({ children, name }: { children: ReactNode; name: string }) {
  return (
    <ErrorBoundary level="module" name={name}>
      {children}
    </ErrorBoundary>
  )
}

/**
 * Panel 级 Error Boundary
 * 用于包裹面板组件（如行情列表面板、K线面板）
 */
export function PanelErrorBoundary({ children, name }: { children: ReactNode; name: string }) {
  return (
    <ErrorBoundary level="panel" name={name}>
      {children}
    </ErrorBoundary>
  )
}

/**
 * Chart 级 Error Boundary
 * 用于包裹图表组件（如 ECharts、PixiJS 渲染器）
 */
export function ChartErrorBoundary({ children, name }: { children: ReactNode; name: string }) {
  return (
    <ErrorBoundary level="chart" name={name}>
      {children}
    </ErrorBoundary>
  )
}

export default ErrorBoundary
