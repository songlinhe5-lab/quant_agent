import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Code2, FileBarChart2, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useStrategyStore } from '../stores'
import { BacktestReport } from './backtest-report'
import { MonacoEditorTab } from './monaco-editor'
import { DiffOverlay } from './diff-overlay'

/**
 * MainTabs — 中列模式切换 ([代码] / [回测报告]).
 * STRAT-07: 把 ⌘1/⌘2 的隐藏模式升为可见 tabs; 本组件即 quant_focus_backtest 事件监听者。
 */
export function MainTabs() {
  const { activeWorkspaceTab, setWorkspaceTab, diff } = useStrategyStore()

  // STRAT-07: 本组件作为 quant_focus_backtest 事件监听者, 修复全仓无监听者的死快捷键
  useEffect(() => {
    const onFocusBacktest = () => setWorkspaceTab('report')
    window.addEventListener('quant_focus_backtest', onFocusBacktest)
    return () => window.removeEventListener('quant_focus_backtest', onFocusBacktest)
  }, [setWorkspaceTab])

  // STRAT-02: When diff is pending, show DiffOverlay instead of regular editor
  if (diff.status === 'pendingDiff') {
    return <DiffOverlay />
  }

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-[oklch(0.09_0.005_270)]">
      {/* 模式 tabs */}
      <div className="h-9 shrink-0 flex items-center gap-2 px-3 border-b border-border/30 bg-secondary/20 text-xs">
        <div className="flex items-center gap-1 rounded-lg bg-background border border-border/40 p-0.5">
          <button
            onClick={() => setWorkspaceTab('code')}
            className={cn(
              'flex items-center gap-1.5 px-3 h-6 rounded-md text-[11px] transition-colors',
              activeWorkspaceTab === 'code'
                ? 'bg-primary/15 text-primary font-semibold'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Code2 className="h-3.5 w-3.5" /> 代码
          </button>
          <button
            onClick={() => setWorkspaceTab('report')}
            className={cn(
              'flex items-center gap-1.5 px-3 h-6 rounded-md text-[11px] transition-colors',
              activeWorkspaceTab === 'report'
                ? 'bg-primary/15 text-primary font-semibold'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <FileBarChart2 className="h-3.5 w-3.5" /> 回测报告
          </button>
        </div>
        <span className="text-muted-foreground/50 text-[10px]">⌘1 / ⌘2 切换</span>
        <div className="grow" />
        {activeWorkspaceTab === 'report' && (
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-amber-500/80 font-mono">SANDBOX · 沙箱推演口径</span>
            <Link
              to="/backtest"
              className="flex items-center gap-1 text-[10px] text-blue-500 hover:text-blue-400 transition-colors"
              title="在独立大规模高频回测引擎中打开 (端点为 /backtest/run/stream)"
            >
              在高频回测引擎中打开 <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        )}
      </div>

      {/* 内容区: 代码 / 回测报告 整区切换 */}
      <div className="flex-1 min-h-0">
        {activeWorkspaceTab === 'code' ? <MonacoEditorTab /> : <BacktestReport />}
      </div>
    </div>
  )
}
