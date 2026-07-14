import { useStrategyStore } from '../stores'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { useConfirmDialog } from '@/components/confirm-dialog'
import { useSandboxRun } from '../hooks/use-sandbox-run'

export function useStrategySandbox() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()

  // STRAT-05: AbortController + debounce + 请求序号
  const { run: runSandbox, cancel: cancelSandboxRun } = useSandboxRun()

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
      // STRAT-05: 使用 useSandboxRun hook (AbortController + 竞态取消)
      const result = await runSandbox({
        source_code: store.code,
        class_name: className,
        params: sanitizedParams,
        ticker: store.testTicker,
        period: store.backtestPeriod,
        initial_capital: parseFloat(store.initialCapital) || 100000,
        data_source: store.dataSource,
        debug_mode: store.isDebugMode,
        data_snapshot_id: store.dataSnapshotId || 'latest_published',
        random_seed: 42,
      })
      if (result?.status === 'success') {
        const report = result.data
        store.setBacktestResult(report)
        const m = report.metrics || report
        if (!isSilent) {
          toast({ title: '✅ 回测推演完成', description: `夏普比率: ${m.sharpe_ratio} | 收益率: ${m.total_return}` })
        }
      } else if (result) {
        toast({ variant: 'destructive', title: '沙箱崩溃', description: result.message })
        store.setRuntimeError(result.message)
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

  return {
    store,
    handleApplyParams,
    handleOptimizeParams,
    handleDeployToOMS,
    handleSavePreset,
    handleDeletePreset,
    applyOptimizedParams,
    cancelSandboxRun, // STRAT-05: 暴露取消方法
  }
}
