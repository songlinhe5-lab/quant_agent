import React, { useEffect, useMemo } from 'react'
import { FolderGit2, Plus, Star, GitBranch, Trash2 } from 'lucide-react'
import { useStrategyStore } from '../stores/useStrategyStore'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

export function LeftSidebar() {
  const store = useStrategyStore()
  const { toast } = useToast()

  useEffect(() => {
    store.fetchStrategies()
    try {
      const f = localStorage.getItem('quant_strategy_favorites')
      if (f) store.setFavorites(JSON.parse(f))
    } catch (e) {}
  }, [])

  const handleToggleFavorite = (name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = store.favorites.includes(name) ? store.favorites.filter(n => n !== name) : [...store.favorites, name]
    store.setFavorites(next)
    localStorage.setItem('quant_strategy_favorites', JSON.stringify(next))
  }

  const handleSelectStrategy = async (name: string) => {
    if (store.isDirty) {
      if (!window.confirm('🚨 当前策略有未保存的修改，确定要放弃修改并切换吗？')) return;
    }
    store.setActiveStrategy(name)
    try {
      const res = await apiClient.get(`/strategy/draft/${name}`)
      if (res.data?.status === 'success') {
        store.setCode(res.data.data.source_code)
        store.setLastSavedCode(res.data.data.source_code)
        store.setIsDirty(false)
        toast({ title: '加载成功', description: `已同步云端 ${name} 策略源码` })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '加载失败', description: e.message })
    }
  }

  const handleDeleteStrategy = async (name: string) => {
    if (!window.confirm(`🚨 确定要彻底删除策略 ${name} 吗？\n该操作无法恢复。`)) return;
    try {
      const res = await apiClient.delete(`/strategy/draft/${name}`)
      if (res.data?.status === 'success') {
        toast({ title: '✅ 删除成功', description: `策略 ${name} 已被物理移除` })
        store.fetchStrategies()
        if (store.activeStrategy === name) {
          store.setCode('')
          store.setLastSavedCode('')
          store.setActiveStrategy('')
          store.setFormSchema([])
          store.setIsDirty(false)
        }
      } else {
        toast({ variant: 'destructive', title: '删除失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    }
  }

  const handleNewStrategy = () => {
    if (store.isDirty) {
      if (!window.confirm('🚨 当前策略有未保存的修改，确定要放弃修改并新建文档吗？')) return;
    }
    store.setActiveStrategy('')
    store.setCode('# Draft Strategy...\n')
    store.setLastSavedCode('')
    store.setFormSchema([])
    store.setIsDirty(false)
  }

  const displayStrategies = useMemo(() => {
    return [...store.strategies].sort((a, b) => {
      const aFav = store.favorites.includes(a.name)
      const bFav = store.favorites.includes(b.name)
      if (aFav && !bFav) return -1
      if (!aFav && bFav) return 1
      return 0
    })
  }, [store.strategies, store.favorites])

  return (
    <div className="h-full flex flex-col bg-background/50">
      <div className="h-9 px-3 border-b border-border/30 flex items-center justify-between shrink-0 bg-secondary/10">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
          <FolderGit2 className="h-3.5 w-3.5"/> 策略草稿库
        </span>
        <button onClick={handleNewStrategy} className="text-muted-foreground hover:text-foreground transition-colors" title="新建策略草稿">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto p-1.5 custom-scrollbar divide-y divide-border/10">
        {displayStrategies.length > 0 ? displayStrategies.map((s) => (
          <li key={s.name} className="relative group rounded-md mb-0.5">
            <div
              onClick={() => handleSelectStrategy(s.name)}
              className={cn(
                'px-2 py-2.5 text-left transition-colors border-l-2 cursor-pointer rounded-r-md',
                store.activeStrategy === s.name
                  ? 'bg-primary/10 border-primary'
                  : 'hover:bg-secondary/40 border-transparent'
              )}
            >
              <div className="flex items-start justify-between gap-1 mb-1.5 pr-6">
                <div className="flex items-center gap-1.5 min-w-0">
                  <button onClick={(e) => handleToggleFavorite(s.name, e)} className="shrink-0 text-muted-foreground hover:text-amber-500 transition-colors">
                    <Star className={cn("h-3 w-3", store.favorites.includes(s.name) && "fill-amber-500 text-amber-500")} />
                  </button>
                  <span className={cn("text-xs font-semibold truncate", store.activeStrategy === s.name ? "text-primary" : "text-foreground")}>{s.name}</span>
                </div>
                <span className={cn(
                  'text-[9px] font-bold px-1.5 py-0.5 rounded flex-shrink-0',
                  s.status === 'active'   ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' :
                  s.status === 'testing'  ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' :
                                            'bg-secondary text-muted-foreground'
                )}>
                  {s.status === 'active' ? '运行' : s.status === 'testing' ? '测试' : '停用'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[9px] text-muted-foreground pl-4">
                <span className="font-mono">{s.lang || 'Python'} · {s.version || 'v1.0'}</span>
                <span className="font-mono">{s.modified ? new Date(s.modified).toLocaleDateString() : ''}</span>
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); handleDeleteStrategy(s.name); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 rounded-md text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-all duration-200 z-10"
              title="删除策略"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </li>
        )) : (
          <div className="p-4 mt-4 text-center flex flex-col items-center gap-2 text-muted-foreground opacity-60">
            <GitBranch className="h-5 w-5" />
            <span className="text-[10px] font-mono">暂无策略记录</span>
          </div>
        )}
      </ul>
    </div>
  )
}
