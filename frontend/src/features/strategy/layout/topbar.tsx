import { Code2, Save, History, FolderOpen, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStrategyStore } from '@/features/strategy/stores'
import { useToast } from '@/hooks/use-toast'

/**
 * Topbar — 草稿名 + 同步状态 + SANDBOX 胶囊 + 版本/草稿库入口.
 * STRAT-07: 删除"运行沙箱 / 部署至 OMS"空壳按钮, 动作入口唯一化到右列底部。
 */
export function Topbar() {
  const { isDirty, formSchema, activeStrategy, saveCode } = useStrategyStore()
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

  const handleShowVersions = () => {
    window.dispatchEvent(new CustomEvent('quant_sidebar_tab', { detail: { tab: 'versions' } }))
  }

  const handleShowDrafts = () => {
    window.dispatchEvent(new CustomEvent('quant_sidebar_tab', { detail: { tab: 'drafts' } }))
  }

  return (
    <div className="h-12 border-b border-border/40 bg-secondary/20 flex items-center justify-between px-4 shrink-0 transition-colors duration-300">
      <div className="flex items-center gap-2 min-w-0">
        <Code2 className="h-4 w-4 text-scene scene-accent-transition shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wide truncate">{displayName}.py</span>
        {isDirty ? (
          <span className="text-[10px] text-amber-500 font-bold ml-1 px-1.5 py-0.5 rounded border border-amber-500/50 bg-amber-500/10 shrink-0">未保存</span>
        ) : (
          <span className="text-[10px] text-muted-foreground ml-1 px-1.5 py-0.5 rounded border border-border/50 shrink-0">已同步</span>
        )}
        {/* 常驻 SANDBOX 胶囊 (宪法 §4: UI 必须显示 SANDBOX/LIVE 横幅) */}
        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full text-amber-500 bg-amber-500/10 border border-amber-500/35 shrink-0 flex items-center gap-1">
          <ShieldCheck className="h-3 w-3" /> SANDBOX · 纸面推演,非实盘
        </span>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <Button size="sm" variant="ghost" onClick={handleShowVersions} className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground">
          <History className="h-3.5 w-3.5" /> 历史版本
        </Button>
        <Button size="sm" variant="ghost" onClick={handleShowDrafts} className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground">
          <FolderOpen className="h-3.5 w-3.5" /> 草稿库
        </Button>
        <Button size="sm" variant="outline" onClick={handleSave} className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground">
          <Save className="h-3.5 w-3.5" /> 保存
        </Button>
      </div>
    </div>
  )
}
