'use client'

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Topbar } from './topbar'
import { LeftSidebar } from './left-sidebar'
import { RightSidebar } from './right-sidebar'
import { BottomTerminal } from './bottom-terminal'
import { MainTabs } from '../workspace/main-tabs'

export function StrategyIDE() {
  return (
    <div className="flex flex-col h-[calc(100vh-100px)] w-full rounded-xl overflow-hidden border border-border/40 shadow-sm bg-background transition-colors duration-300">
      {/* Top Global Actions */}
      <Topbar />

      {/* Main IDE Area */}
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left Sidebar: Explorer */}
        <ResizablePanel defaultSize={15} minSize={10} maxSize={25} className="bg-secondary/10">
          <LeftSidebar />
        </ResizablePanel>

        <ResizableHandle withHandle className="bg-border/40 hover:bg-primary/50 transition-colors" />

        {/* Center: Editor & Terminal */}
        <ResizablePanel defaultSize={60}>
          <ResizablePanelGroup direction="vertical">
            <ResizablePanel defaultSize={75} minSize={30}>
              <MainTabs />
            </ResizablePanel>
            <ResizableHandle withHandle className="bg-border/40 hover:bg-primary/50 transition-colors" />
            <ResizablePanel defaultSize={25} minSize={10}>
              <BottomTerminal />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>

        <ResizableHandle withHandle className="bg-border/40 hover:bg-primary/50 transition-colors" />

        {/* Right Sidebar: AI Copilot & Parameters */}
        <ResizablePanel defaultSize={25} minSize={20} maxSize={40}>
          <RightSidebar />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}