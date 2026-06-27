import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Code2, LineChart } from 'lucide-react'
import { useStrategyStore } from '../stores/useStrategyStore'
import { BacktestReport } from './backtest-report'
import { MonacoEditorTab } from './monaco-editor'

export function MainTabs() {
  const { activeWorkspaceTab, setWorkspaceTab } = useStrategyStore()

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-[oklch(0.09_0.005_270)]">
      <Tabs value={activeWorkspaceTab} onValueChange={(v) => setWorkspaceTab(v as any)} className="flex flex-col h-full">
        <TabsList className="bg-secondary/20 p-0 h-9 border-b border-border/30 rounded-none w-full justify-start px-2 shrink-0">
          <TabsTrigger value="code" className="text-xs px-4 h-9 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1.5"><Code2 className="h-3.5 w-3.5"/> 策略源码 (Monaco)</TabsTrigger>
          <TabsTrigger value="report" className="text-xs px-4 h-9 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1.5"><LineChart className="h-3.5 w-3.5"/> 全屏回测报告</TabsTrigger>
        </TabsList>
        
        <div className="flex-1 overflow-hidden relative">
          <TabsContent value="code" className="m-0 h-full w-full absolute inset-0 flex flex-col">
            <MonacoEditorTab />
          </TabsContent>
          <TabsContent value="report" className="m-0 h-full w-full flex flex-col items-center justify-start absolute inset-0 overflow-y-auto">
            <BacktestReport />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}