import { useState } from 'react'
import { Code2, LineChart, PanelBottomClose, PanelBottomOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { useStrategyStore } from '../stores'
import { BacktestReport } from './backtest-report'
import { MonacoEditorTab } from './monaco-editor'
import { DiffOverlay } from './diff-overlay'

export function MainTabs() {
  const { activeWorkspaceTab, setWorkspaceTab, diff } = useStrategyStore()
  // PROD-10: 'report' => 打开底部回测报告面板（代码始终可见）；'code' => 仅代码
  const reportOpen = activeWorkspaceTab === 'report'

  // STRAT-02: When diff is pending, show DiffOverlay instead of regular editor
  if (diff.status === 'pendingDiff') {
    return <DiffOverlay />
  }

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-[oklch(0.09_0.005_270)]">
      {/* PROD-10: 顶部工具栏——代码始终可见，右侧按钮切换底部回测报告面板 */}
      <div className="h-9 shrink-0 flex items-center gap-2 px-3 border-b border-border/30 bg-secondary/20 text-xs">
        <span className="flex items-center gap-1.5 text-foreground/80 font-medium">
          <Code2 className="h-3.5 w-3.5" /> 策略源码 (Monaco)
        </span>
        <span className="text-muted-foreground/40">·</span>
        <button
          onClick={() => setWorkspaceTab(reportOpen ? 'code' : 'report')}
          className={cn(
            'ml-auto flex items-center gap-1.5 px-2.5 h-6 rounded border text-[11px] transition-colors',
            reportOpen
              ? 'bg-primary/15 text-primary border-primary/30 hover:bg-primary/25'
              : 'bg-background text-muted-foreground border-border/50 hover:bg-secondary hover:text-foreground',
          )}
        >
          {reportOpen ? <PanelBottomClose className="h-3.5 w-3.5" /> : <PanelBottomOpen className="h-3.5 w-3.5" />}
          {reportOpen ? '隐藏回测报告' : '查看回测报告'}
        </button>
      </div>

      {/* PROD-10: 代码常驻（始终挂载，保留滚动位置）；报告为可缩放底部面板，开/关不影响代码实例 */}
      <div className="flex-1 min-h-0">
        <ResizablePanelGroup direction="vertical" className="h-full">
          <ResizablePanel id="editor" order={1} defaultSize={reportOpen ? 55 : 100} minSize={20}>
            <MonacoEditorTab />
          </ResizablePanel>
          {reportOpen && <ResizableHandle withHandle />}
          {reportOpen && (
            <ResizablePanel id="report" order={2} defaultSize={45} minSize={15}>
              <BacktestReport />
            </ResizablePanel>
          )}
        </ResizablePanelGroup>
      </div>
    </div>
  )
}
