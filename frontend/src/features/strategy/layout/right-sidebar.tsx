import React, { useState, useEffect } from 'react'
import { Bot, Settings2, Code2, Save, X, Plus, Play, Rocket, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AIChat } from './ai-chat'
import { DynamicStrategyForm } from '../dynamic-strategy-form'
import { useStrategySandbox } from './use-strategy-sandbox'
import { SandboxEnvForm } from './sandbox-env-form'
import { useStrategyStore } from '../stores'
import { useDeployGate } from './use-deploy-gate'

/**
 * RightSidebar — AI 副驾 (右列)。自上而下:
 *  Copilot 对话 -> 动态参数表单 -> 沙箱环境表单 -> 动作按钮(唯一入口)。
 * STRAT-07: 删除 Topbar 空壳按钮, 动作入口唯一化于此。
 */
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

  const { openDeployGate, gateDialog } = useDeployGate()

  // PROD-04e: 响应 ⌘3 快捷键，聚焦 AI 对话输入框
  useEffect(() => {
    const onFocusAi = () => {
      setTimeout(() => window.dispatchEvent(new CustomEvent('quant_focus_ai_input')), 60)
    }
    window.addEventListener('quant_focus_ai_chat', onFocusAi)
    return () => window.removeEventListener('quant_focus_ai_chat', onFocusAi)
  }, [])

  // 主按钮"运行沙箱"使用当前 schema 首个类的默认参数 (动作入口唯一且真实可用)
  const primaryClassName = store.formSchema[0]?.class_name || ''
  const buildDefaultParams = () => {
    const strat = store.formSchema[0]
    if (!strat) return {}
    const params: Record<string, any> = {}
    strat.parameters.forEach((p: any) => {
      params[p.name] = p.default !== null && p.default !== undefined ? p.default : (p.type === 'bool' ? false : '')
    })
    return params
  }

  const handleRunSandbox = () => {
    if (!primaryClassName) {
      return
    }
    handleApplyParams(primaryClassName, buildDefaultParams())
  }

  const handleDeployClick = () => {
    if (!primaryClassName) return
    openDeployGate({ className: primaryClassName, params: buildDefaultParams() })
  }

  const isRunning = store.isSimulating || store.isOptimizing

  return (
    <div className="h-full flex flex-col bg-secondary/5 overflow-hidden">
      {/* Copilot 对话 */}
      <div className="flex-1 min-h-0 border-b border-border/30">
        <div className="h-9 px-3 border-b border-border/30 bg-secondary/20 flex items-center gap-2 shrink-0">
          <Bot className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">AI 副驾 · Copilot</span>
          <span className="ml-auto text-[10px] text-muted-foreground">⌘3 聚焦</span>
        </div>
        <AIChat />
      </div>

      {/* 动态参数 + 沙箱环境 */}
      <div className="shrink-0 max-h-[42%] overflow-y-auto p-3 custom-scrollbar space-y-3">
        <div className="flex items-center gap-2 mb-1">
          <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">动态参数</span>
          <span className="text-[9px] text-muted-foreground/60">schema 来自 parse-config</span>
          {store.formSchema.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleSavePreset} className="h-6 px-2 text-[10px] gap-1.5 ml-auto bg-background hover:bg-scene/10 hover:text-scene hover:border-scene/30 shrink-0">
              <Plus className="h-3 w-3" /> 保存参数
            </Button>
          )}
        </div>

        {/* 参数预设标签栏 */}
        {store.formSchema.length > 0 && (() => {
          const currentClassName = store.formSchema[0]?.class_name || '';
          const presets = Object.entries(store.savedPresets).filter(([k]) => k.startsWith(`${currentClassName}::`));
          if (presets.length === 0) return null;
          return (
            <div className="flex flex-wrap items-center gap-1.5">
              {presets.map(([k, params]) => {
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
              })}
            </div>
          )
        })()}

        {store.formSchema.length > 0 ? (
          <DynamicStrategyForm
            schema={store.formSchema}
            onSubmit={handleApplyParams}
            onOptimize={handleOptimizeParams}
            onDeploy={undefined}
          />
        ) : (
          <div className="flex flex-col items-center justify-center py-8 border border-dashed border-border/50 rounded-xl bg-secondary/10 text-muted-foreground">
            <Code2 className="h-6 w-6 mb-2 opacity-20" />
            <p className="text-[10px] font-mono text-center">左侧编辑器的类初始化参数<br/>将在此处实时映射为表单</p>
          </div>
        )}

        {/* 沙箱环境 */}
        <SandboxEnvForm />
      </div>

      {/* 动作入口 (唯一) */}
      <div className="shrink-0 p-3 border-t border-border/30 bg-secondary/20 space-y-2">
        <Button
          onClick={handleRunSandbox}
          disabled={!primaryClassName || isRunning}
          className="w-full h-9 text-xs gap-1.5 bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
        >
          {isRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          {isRunning ? '沙箱运行中...' : '▶ 运行沙箱'}
        </Button>
        <Button
          onClick={handleDeployClick}
          disabled={!primaryClassName}
          variant="outline"
          className="w-full h-8 text-[11px] gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <Rocket className="h-3.5 w-3.5" /> 部署至 OMS…
        </Button>
      </div>

      {gateDialog}
    </div>
  )
}
