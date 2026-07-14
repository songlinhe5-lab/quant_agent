import { Play, Save, Rocket, Code2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStrategyStore } from '@/features/strategy/stores'
import { useToast } from '@/hooks/use-toast'

export function Topbar() {
  const { isDirty, formSchema, activeStrategy, saveCode, setWorkspaceTab } = useStrategyStore()
  const { toast } = useToast()
  const displayName = activeStrategy || (formSchema.length > 0 ? formSchema[0].class_name : 'UntitledStrategy')

  const handleSave = async () => {
    const className = formSchema.length > 0 ? formSchema[0].class_name : 'DraftStrategy'
    const result = await saveCode(className)
    if (result.success) {
      toast({ title: '✅ 保存成功', description: '策略脚本已成功同步至后端工作区。' })
    } else {
      toast({ variant: 'destructive', title: '保存失败', description: result.message })
    }
  }

  const handleRunSandbox = () => {
    // STRAT-05 将完善：此处先跳转到代码编辑器，用户可通过右侧参数面板触发
    setWorkspaceTab('code')
    toast({ title: '💡 提示', description: '请在右侧参数面板点击「应用推演」以运行沙箱。' })
  }

  const handleDeploy = () => {
    // STRAT-05 将完善：此处先跳转到参数面板
    setWorkspaceTab('code')
    toast({ title: '💡 提示', description: '请在右侧参数面板点击「部署实盘」以部署至 OMS。' })
  }

  return (
    <div className="h-12 border-b border-border/40 bg-secondary/20 flex items-center justify-between px-4 shrink-0 transition-colors duration-300">
      <div className="flex items-center gap-2">
        <Code2 className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold uppercase tracking-wide">{displayName}.py</span>
        {isDirty ? (
          <span className="text-[10px] text-amber-500 font-bold ml-2 px-1.5 py-0.5 rounded border border-amber-500/50 bg-amber-500/10">未保存 (Unsaved)</span>
        ) : (
          <span className="text-[10px] text-muted-foreground ml-2 px-1.5 py-0.5 rounded border border-border/50">已同步</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={handleSave} className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground"><Save className="h-3.5 w-3.5"/> 保存</Button>
        <Button size="sm" variant="outline" onClick={handleRunSandbox} className="h-7 text-xs gap-1.5 border-emerald-500/30 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"><Play className="h-3.5 w-3.5"/> 运行沙箱</Button>
        <Button size="sm" onClick={handleDeploy} className="h-7 text-xs gap-1.5 bg-primary/10 text-primary shadow-none hover:bg-primary/20"><Rocket className="h-3.5 w-3.5"/> 部署至 OMS</Button>
      </div>
    </div>
  )
}