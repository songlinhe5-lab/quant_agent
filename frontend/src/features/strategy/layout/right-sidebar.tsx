import React from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Bot, Settings2, Code2, Save, X, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AIChat } from './ai-chat'
import { DynamicStrategyForm } from '../dynamic-strategy-form'
import { useStrategyStore } from '../stores/useStrategyStore'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { useConfirmDialog } from '@/components/confirm-dialog'

export function RightSidebar() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()

  // 💡 沙箱回测引擎：提取表单参数并抛给后端执行推演
  const handleApplyParams = async (className: string, data: Record<string, any>, isSilent: boolean = false) => {
    if (!isSilent) {
      toast({ title: '🚀 启动沙箱推演', description: `正在挂载 ${className} 策略与历史数据...` })
      store.setBacktestResult(null)
    }
    store.setSimulating(true)
    store.setRuntimeError(null)
    store.setWorkspaceTab('report') // 自动跳转到报告 Tab
    
    // 清洗参数：网格语法降级为单次探测
    const sanitizedParams = { ...data }
    store.formSchema.find(s => s.class_name === className)?.parameters.forEach((p: any) => {
      let val = sanitizedParams[p.name];
      if (val === '' || val === undefined || val === null) val = p.default;
      
      if ((p.type === 'int' || p.type === 'float') && typeof val === 'string') {
        const firstNumStr = val.split(/[:,]/)[0]
        const parsed = p.type === 'int' ? parseInt(firstNumStr) : parseFloat(firstNumStr);
        sanitizedParams[p.name] = !isNaN(parsed) ? parsed : (p.default || 0);
      } else {
        sanitizedParams[p.name] = val;
      }
    });
    
    store.setLastUsedClassName(className)
    store.setLastUsedParams(sanitizedParams)
    
    try {
      const res = await apiClient.post('/strategy/run-sandbox', {
        source_code: store.code,
        class_name: className,
        params: sanitizedParams,
        ticker: store.testTicker,
        period: store.backtestPeriod,
        initial_capital: parseFloat(store.initialCapital) || 100000,
        data_source: store.dataSource,
        debug_mode: store.isDebugMode
      })
      if (res.data?.status === 'success') {
        const report = res.data.data
        store.setBacktestResult(report)
        const m = report.metrics || report
        if (!isSilent) {
          toast({ title: '✅ 回测推演完成', description: `夏普比率: ${m.sharpe_ratio} | 收益率: ${m.total_return}` })
        }
      } else {
        toast({ variant: 'destructive', title: '沙箱崩溃', description: res.data?.message })
        store.setRuntimeError(res.data?.message)
      }
    } catch (e: any) {
      if (e.name !== 'CanceledError' && e.message !== 'canceled') {
        toast({ variant: 'destructive', title: '网络异常', description: e.message })
        store.setRuntimeError(e.message)
      }
    } finally {
      store.setSimulating(false)
    }
  }

  // 💡 参数网格搜索与寻优
  const handleOptimizeParams = async (className: string, data: Record<string, any>) => {
    if (!store.formSchema) return;
    toast({ title: '🔍 启动智能寻优', description: '正在构建参数网格并进行全空间回测...' })
    store.setOptimizing(true)
    store.setOptimizationResults(null)
    store.setOptimizedClassName(className)
    store.setRuntimeError(null)
    store.setWorkspaceTab('report') // 自动跳转到报告 Tab
    
    const paramGrid: Record<string, any[]> = {};
    const currentSchema = store.formSchema.find(s => s.class_name === className);
    
    if (currentSchema) {
      currentSchema.parameters.forEach((p: any) => {
        let val = data[p.name];
        if (val === '' || val === undefined || val === null) val = p.default;
        
        if (p.type === 'bool') {
            paramGrid[p.name] = [true, false];
        } else if (p.options && Array.isArray(p.options)) {
            paramGrid[p.name] = p.options;
        } else if (p.type === 'int' || p.type === 'float') {
            if (typeof val === 'string') {
                if (val.includes(':')) {
                    const parts = val.split(':').map(Number);
                    if (parts.length === 3 && !parts.some(isNaN)) {
                        const [start, end, step] = parts;
                        const arr = [];
                        for (let i = start; i <= end; i += step) arr.push(p.type === 'int' ? Math.round(i) : Number(i.toFixed(4)));
                        paramGrid[p.name] = arr;
                        return;
                    }
                } else if (val.includes(',')) {
                    paramGrid[p.name] = val.split(',').map(Number).filter(n => !isNaN(n));
                    return;
                }
            }
            const num = p.type === 'int' ? parseInt(val) : parseFloat(val);
            const validNum = !isNaN(num) ? num : (p.default || (p.type === 'int' ? 10 : 1.0));
            if (p.type === 'int') {
                paramGrid[p.name] = [Math.max(1, Math.floor(validNum * 0.5)), validNum, Math.floor(validNum * 1.5)];
            } else {
                paramGrid[p.name] = [Number((validNum * 0.8).toFixed(2)), validNum, Number((validNum * 1.2).toFixed(2))];
            }
        } else {
            paramGrid[p.name] = [val];
        }
      });
    }

    try {
      const res = await apiClient.post('/strategy/optimize-sandbox', {
        source_code: store.code,
        class_name: className,
        param_grid: paramGrid,
        ticker: store.testTicker,
        period: store.backtestPeriod,
        target_metric: "sharpe_ratio",
        initial_capital: parseFloat(store.initialCapital) || 100000,
        data_source: store.dataSource
      })
      
      if (res.data?.status === 'success') {
        store.setOptimizationResults(res.data.data)
        toast({ title: '✅ 寻优完成', description: `共找到 ${res.data.data.length} 组优质参数组合` })
      } else {
        toast({ variant: 'destructive', title: '寻优失败', description: res.data?.message })
        store.setRuntimeError(res.data?.message)
      }
    } catch (e: any) {
      if (e.name !== 'CanceledError' && e.message !== 'canceled') {
        toast({ variant: 'destructive', title: '执行异常', description: e.message })
        store.setRuntimeError(e.message)
      }
    } finally {
      store.setOptimizing(false)
    }
  }

  // 💡 实盘一键部署引擎
  const handleDeployToOMS = async (className: string, data: Record<string, any>) => {
    toast({ title: '🚀 部署初始化', description: `正在将 ${className} 编译并持久化至底层 OMS 引擎...` })
    
    const sanitizedParams = { ...data }
    store.formSchema.find(s => s.class_name === className)?.parameters.forEach((p: any) => {
      let val = sanitizedParams[p.name];
      if (val === '' || val === undefined || val === null) val = p.default;
      
      if ((p.type === 'int' || p.type === 'float') && typeof val === 'string') {
        const firstNumStr = val.split(/[:,]/)[0]
        const parsed = p.type === 'int' ? parseInt(firstNumStr) : parseFloat(firstNumStr);
        sanitizedParams[p.name] = !isNaN(parsed) ? parsed : (p.default || 0);
      } else {
        sanitizedParams[p.name] = val;
      }
    });

    try {
      const res = await apiClient.post('/strategy/deploy-to-oms', {
        source_code: store.code,
        class_name: className,
        params: sanitizedParams,
        ticker: store.testTicker,
        period: store.backtestPeriod,
        initial_capital: parseFloat(store.initialCapital) || 100000,
        data_source: store.dataSource
      })
      if (res.data?.status === 'success') {
        toast({ title: '✅ 部署成功', description: '策略已挂载至实盘节点，请前往【OMS与算力节点】查看运行状态！' })
      } else {
        toast({ variant: 'destructive', title: '部署失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    }
  }

  // 💡 参数预设本地存取逻辑
  const handleSavePreset = () => {
    if (!store.lastUsedClassName || Object.keys(store.lastUsedParams).length === 0) {
      toast({ variant: 'destructive', title: '无法保存', description: '请先运行一次回测，以确认当前参数组合有效。' })
      return
    }
    const presetName = window.prompt('请输入预设名称 (例如: 激进型参数):', '新预设')
    if (!presetName) return

    const key = `${store.lastUsedClassName}::${presetName}`
    const next = { ...store.savedPresets, [key]: store.lastUsedParams }
    store.setSavedPresets(next)
    localStorage.setItem('quant_strategy_presets', JSON.stringify(next))
    toast({ title: '✅ 预设已保存', description: `参数预设 "${presetName}" 已存入本地。` })
  }

  const handleDeletePreset = async (key: string) => {
    const ok = await confirm({ title: '删除参数预设', description: '确定要删除这个参数预设吗？', confirmLabel: '删除' })
    if (!ok) return
    const next = { ...store.savedPresets }
    delete next[key]
    store.setSavedPresets(next)
    localStorage.setItem('quant_strategy_presets', JSON.stringify(next))
  }

  // 💡 运用预设/寻优参数并直接注入左侧代码源码
  const applyOptimizedParams = (className: string, params: any) => {
    let updatedCode = store.code;

    const currentSchema = store.formSchema.find((s: any) => s.class_name === className);
    if (currentSchema) {
      currentSchema.parameters.forEach((p: any) => {
        if (params[p.name] !== undefined) {
          let valStr = String(params[p.name]);
          if (p.type === 'str' || typeof params[p.name] === 'string') {
            valStr = `'${params[p.name]}'`;
          } else if (p.type === 'bool') {
            valStr = params[p.name] ? 'True' : 'False';
          }
          const regex = new RegExp(`((?<!\\.)\\b${p.name}\\b\\s*:\\s*[^=]+=\\s*)([^,\\)\\n]+)`, 'g');
          updatedCode = updatedCode.replace(regex, `$1${valStr}`);
        }
      });
    }

    if (updatedCode !== store.code) {
      store.setCode(updatedCode);
    }

    store.setFormSchema(
      store.formSchema.map((s: any) => {
        if (s.class_name === className) {
          return {
            ...s,
            parameters: s.parameters.map((p: any) => {
              if (params[p.name] !== undefined) {
                return { ...p, default: params[p.name] };
              }
              return p;
            })
          };
        }
        return s;
      })
    );
    handleApplyParams(className, params);
  }

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
          {/* 1. 沙箱环境配置 */}
          <div className="flex flex-col gap-3 p-3 bg-secondary/20 border border-border/30 rounded-xl animate-in fade-in">
            <div className="flex items-center gap-2 mb-1">
              <Settings2 className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs font-semibold text-muted-foreground tracking-wide uppercase">沙箱环境配置</span>
            </div>
            
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] text-muted-foreground font-mono">测试标的</span>
                <input 
                  type="text" 
                  value={store.testTicker} 
                  onChange={(e) => store.setTestTicker(e.target.value.toUpperCase())}
                  className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary uppercase transition-all"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] text-muted-foreground font-mono">初始资金</span>
                <input 
                  type="number" 
                  value={store.initialCapital} 
                  onChange={(e) => store.setInitialCapital(e.target.value)}
                  className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary transition-all"
                  step="10000"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] text-muted-foreground font-mono">回测时长</span>
                <select
                  value={store.backtestPeriod}
                  onChange={(e) => store.setBacktestPeriod(e.target.value)}
                  className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary cursor-pointer transition-all"
                >
                  <option value="1mo">1 个月</option>
                  <option value="3mo">3 个月</option>
                  <option value="6mo">6 个月</option>
                  <option value="1y">1 年</option>
                  <option value="2y">2 年</option>
                  <option value="5y">5 年</option>
                  <option value="max">全部历史</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] text-muted-foreground font-mono">数据源</span>
                <select
                  value={store.dataSource}
                  onChange={(e) => store.setDataSource(e.target.value)}
                  className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary cursor-pointer transition-all"
                >
                  <option value="auto">智能路由</option>
                  <option value="futu">富途 OpenD</option>
                  <option value="yfinance">Yahoo</option>
                </select>
              </div>
            </div>
            
            <div className="flex items-center gap-1.5 pt-1 border-t border-border/30">
              <input 
                type="checkbox" 
                id="debugMode" 
                checked={store.isDebugMode} 
                onChange={(e) => store.setIsDebugMode(e.target.checked)}
                className="rounded-sm border-border accent-primary focus:ring-primary/30 w-3 h-3 cursor-pointer"
              />
              <label htmlFor="debugMode" className="text-[10px] text-muted-foreground font-mono cursor-pointer select-none">记录内部调试日志</label>
            </div>
          </div>

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