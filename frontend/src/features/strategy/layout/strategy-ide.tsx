'use client'

import { useEffect } from 'react'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Topbar } from './topbar'
import { LeftSidebar } from './left-sidebar'
import { RightSidebar } from './right-sidebar'
import { BottomTerminal } from './bottom-terminal'
import { MainTabs } from '../workspace/main-tabs'
import { useStrategyStore } from '../stores'
import { cn } from '@/lib/utils'

export function StrategyIDE({ className }: { className?: string }) {
  const enterDiff = useStrategyStore(s => s.enterDiff)
  const setWorkspaceTab = useStrategyStore(s => s.setWorkspaceTab)

  // PROD-04e: 研究模式键盘优先交互（Cmd+1/2/3 快速跳转面板）
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return
      if (e.key === '1') {
        e.preventDefault()
        setWorkspaceTab('code')
        window.dispatchEvent(new CustomEvent('quant_focus_code'))
      } else if (e.key === '2') {
        e.preventDefault()
        setWorkspaceTab('report')
        window.dispatchEvent(new CustomEvent('quant_focus_backtest'))
      } else if (e.key === '3') {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('quant_focus_ai_chat'))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [setWorkspaceTab])

  // 💡 监听来自 Copilot 的策略代码部署事件
  useEffect(() => {
    // 1. 监听自定义事件（SPA 内无刷新跳转）
    const handleStrategyCodeInvoke = (e: Event) => {
      const customEvent = e as CustomEvent<{ code: string }>
      if (customEvent.detail?.code) {
        enterDiff(customEvent.detail.code, 'hermes')
        setWorkspaceTab('code')
      }
    }
    window.addEventListener('quant_strategy_code_invoke', handleStrategyCodeInvoke)

    // 2. 检查 sessionStorage（兼容直接页面跳转场景）
    const savedCode = sessionStorage.getItem('quant_strategy_initial_code')
    if (savedCode) {
      enterDiff(savedCode, 'hermes')
      setWorkspaceTab('code')
      sessionStorage.removeItem('quant_strategy_initial_code')
    }

    return () => window.removeEventListener('quant_strategy_code_invoke', handleStrategyCodeInvoke)
  }, [enterDiff, setWorkspaceTab])

  return (
    <div
      className={cn(
        'relative flex flex-col w-full rounded-xl overflow-hidden border border-border/40 shadow-sm bg-background transition-colors duration-300 scene-accent-transition',
        className ?? 'h-[calc(100vh-100px)]',
      )}
    >
      {/* Top Global Actions */}
      <Topbar />

      {/* Main IDE Area */}
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left Sidebar: Explorer */}
        <ResizablePanel defaultSize={15} minSize={10} maxSize={25} className="bg-secondary/10">
          <LeftSidebar />
        </ResizablePanel>

        <ResizableHandle withHandle className="bg-border/40 hover:bg-scene/50 transition-colors scene-accent-transition" />

        {/* Center: Editor & Terminal */}
        <ResizablePanel defaultSize={60}>
          <ResizablePanelGroup direction="vertical">
            <ResizablePanel defaultSize={75} minSize={30}>
              <MainTabs />
            </ResizablePanel>
            <ResizableHandle withHandle className="bg-border/40 hover:bg-scene/50 transition-colors scene-accent-transition" />
            <ResizablePanel defaultSize={25} minSize={10}>
              <BottomTerminal />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>

        <ResizableHandle withHandle className="bg-border/40 hover:bg-scene/50 transition-colors scene-accent-transition" />

        {/* Right Sidebar: AI Copilot & Parameters */}
        <ResizablePanel defaultSize={25} minSize={20} maxSize={40}>
          <RightSidebar />
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* PROD-04e: 键盘优先交互快捷键提示 */}
      <div className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3 text-[9px] font-mono text-muted-foreground/70 bg-background/70 backdrop-blur px-2.5 py-0.5 rounded-full border border-border/30">
        <span><kbd className="text-scene">⌘1</kbd> 代码</span>
        <span><kbd className="text-scene">⌘2</kbd> 回测</span>
        <span><kbd className="text-scene">⌘3</kbd> AI 助手</span>
      </div>
    </div>
  )
}