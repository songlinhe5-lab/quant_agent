import React from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Bot, Settings2, Code2, Save, X, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AIChat } from './ai-chat'
import { DynamicStrategyForm } from '../dynamic-strategy-form'
import { useStrategySandbox } from './use-strategy-sandbox'
import { SandboxEnvForm } from './sandbox-env-form'

export function RightSidebar() {
  const {
    store,
    handleApplyParams,
    handleOptimizeParams,
    handleDeployToOMS,
    handleSavePreset,
    handleDeletePreset,
    applyOptimizedParams,
  } = useStrategySandbox()

  return (
    <div className="h-full flex flex-col bg-secondary/5">
      <Tabs defaultValue="chat" className="flex flex-col h-full">
        <TabsList className="bg-secondary/20 p-0 h-9 border-b border-border/30 rounded-none w-full justify-start px-2 shrink-0">
          <TabsTrigger value="chat" className="text-xs px-4 h-9 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1.5"><Bot className="h-3.5 w-3.5"/> AI Copilot</TabsTrigger>
          <TabsTrigger value="config" className="text-xs px-4 h-9 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1.5"><Settings2 className="h-3.5 w-3.5"/> 动态参数</TabsTrigger>
        </TabsList>
        
        {/* AI Copilot Tab */}
        <TabsContent value="chat" className="m-0 flex-1 flex flex-col overflow-hidden relative">
          <AIChat />
        </TabsContent>
        
        {/* AST 参数配置 Tab */}
        <TabsContent value="config" className="m-0 flex-1 overflow-y-auto p-4 custom-scrollbar">
          <SandboxEnvForm />

          {/* 2. 动态参数提取表单 */}
          {store.formSchema.length > 0 ? (
            <div className="flex flex-col gap-3 animate-in fade-in slide-in-from-bottom-2 mt-4">
              {/* 参数预设标签栏 */}
              <div className="flex flex-col gap-2 p-2.5 bg-secondary/10 border border-border/30 rounded-xl">
                <div className="flex items-center justify-between border-b border-border/30 pb-1.5">
                  <span className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider flex items-center gap-1">
                    <Save className="h-3 w-3" /> 参数预设:
                  </span>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={handleSavePreset} 
                    className="h-6 px-2.5 text-[10px] gap-1.5 bg-background hover:bg-primary/10 hover:text-primary hover:border-primary/30 transition-all shrink-0"
                  >
                    <Plus className="h-3 w-3" /> 保存参数
                  </Button>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  {(() => {
                    const currentClassName = store.formSchema[0]?.class_name || '';
                    const presets = Object.entries(store.savedPresets).filter(([k]) => k.startsWith(`${currentClassName}::`));
                    
                    if (presets.length === 0) {
                      return <span className="text-[10px] text-muted-foreground italic opacity-70">暂无本地预设</span>;
                    }
                    
                    return presets.map(([k, params]) => {
                      const name = k.split('::')[1];
                      return (
                        <div key={k} className="group flex items-center gap-1 bg-background border border-border/50 rounded-full pl-2.5 pr-1 py-0.5 hover:border-primary/50 transition-all shadow-sm">
                          <span 
                            className="text-[10px] text-foreground font-medium cursor-pointer hover:text-primary transition-colors" 
                            onClick={() => applyOptimizedParams(currentClassName, params)} 
                            title="一键将该预设参数覆盖到源码中并执行回测"
                          >
                            {name}
                          </span>
                          <button 
                            onClick={(e) => { e.stopPropagation(); handleDeletePreset(k); }} 
                            className="p-0.5 rounded-full text-muted-foreground hover:bg-red-500/10 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                            title="删除预设"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      )
                    });
                  })()}
                </div>
              </div>
              
              {/* AST 参数渲染组件 */}
              <DynamicStrategyForm 
                schema={store.formSchema} 
                onSubmit={handleApplyParams} 
                onOptimize={handleOptimizeParams}
                onDeploy={handleDeployToOMS}
              />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-10 border border-dashed border-border/50 rounded-xl bg-secondary/10 text-muted-foreground mt-4">
              <Code2 className="h-8 w-8 mb-3 opacity-20" />
              <p className="text-xs font-mono text-center">左侧编辑器的类初始化参数<br/>将在此处实时映射为表单</p>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
