import React, { useEffect, useMemo, useState } from 'react'
import { FolderGit2, Plus, Star, GitBranch, Trash2, Clock, ChevronDown, ChevronRight } from 'lucide-react'
import { useStrategyStore } from '../stores'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { useConfirmDialog } from '@/components/confirm-dialog-context'
import { cn } from '@/lib/utils'
import { VersionTimeline } from './version-timeline'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'bg-secondary text-muted-foreground' },
  backtested: { label: '已回测', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  deployed: { label: '已部署', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
}

// ─────────────────────────────────────────────────────────────
// STRAT-07: 模板中心 (空白 / RSI / 网格 / 突破跟随) — 新建即带 BaseStrategy 骨架
// ─────────────────────────────────────────────────────────────
const BLANK_SKELETON = `from backend.backtest import BaseStrategySandbox as BaseStrategy


class MyStrategy(BaseStrategy):
    """示例策略: 继承 BaseStrategy, 在 on_bar 中实现逻辑"""

    def __init__(self, pos_pct: float = 0.05):
        self.pos_pct = pos_pct

    def on_bar(self, ctx):
        # TODO: 在这里编写你的策略逻辑
        pass
`

const TEMPLATES: Array<{ id: string; name: string; desc: string; code: string }> = [
  {
    id: 'blank',
    name: '空白模板',
    desc: '最小可运行骨架, 直接通过架构检查',
    code: BLANK_SKELETON,
  },
  {
    id: 'rsi',
    name: 'RSI 双均线',
    desc: '超卖买入 / 超买卖出, 单标的',
    code: `from backend.backtest import BaseStrategySandbox as BaseStrategy


class RsiReversalStrategy(BaseStrategy):
    """RSI 反转: 超卖区间买入, 超买区间卖出"""

    def __init__(self, rsi_period: int = 14, pos_pct: float = 0.05):
        self.rsi_period = rsi_period
        self.pos_pct = pos_pct

    def on_bar(self, ctx):
        rsi = ctx.indicators.rsi(self.rsi_period)
        if rsi < 30 and not ctx.position:
            ctx.buy(percent=self.pos_pct)
        elif rsi > 70 and ctx.position:
            ctx.sell_all()
`,
  },
  {
    id: 'grid',
    name: '网格',
    desc: '等距网格挂单, 适合震荡市',
    code: `from backend.backtest import BaseStrategySandbox as BaseStrategy


class GridStrategy(BaseStrategy):
    """等距网格: 围绕成本价上下按网格间距挂单"""

    def __init__(self, grid_size: float = 0.02, levels: int = 5):
        self.grid_size = grid_size
        self.levels = levels

    def on_bar(self, ctx):
        # TODO: 实现等距网格挂单逻辑
        pass
`,
  },
  {
    id: 'breakout',
    name: '突破跟随',
    desc: 'N 周期新高突破追入 + 跟踪止损',
    code: `from backend.backtest import BaseStrategySandbox as BaseStrategy


class BreakoutFollowStrategy(BaseStrategy):
    """N 周期新高突破追入 + 跟踪止损"""

    def __init__(self, lookback: int = 20, stop_pct: float = 0.05):
        self.lookback = lookback
        self.stop_pct = stop_pct

    def on_bar(self, ctx):
        # TODO: 实现突破追入 + 跟踪止损逻辑
        pass
`,
  },
]

export function LeftSidebar() {
  const store = useStrategyStore()
  const { toast } = useToast()
  const { confirm } = useConfirmDialog()
  const [sideTab, setSideTab] = useState('drafts')
  const [tplOpen, setTplOpen] = useState(false)

  useEffect(() => {
    store.fetchStrategies()
    try {
      const f = localStorage.getItem('quant_strategy_favorites')
      if (f) store.setFavorites(JSON.parse(f))
    } catch (_e) { /* ignore */ }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // STRAT-07: Topbar 的"草稿库 / 历史版本"入口切换到对应左侧栏 tab
  useEffect(() => {
    const onSidebarTab = (e: Event) => {
      const tab = (e as CustomEvent<{ tab?: string }>).detail?.tab
      if (tab) setSideTab(tab)
    }
    window.addEventListener('quant_sidebar_tab', onSidebarTab)
    return () => window.removeEventListener('quant_sidebar_tab', onSidebarTab)
  }, [])

  const handleToggleFavorite = (name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = store.favorites.includes(name) ? store.favorites.filter(n => n !== name) : [...store.favorites, name]
    store.setFavorites(next)
    localStorage.setItem('quant_strategy_favorites', JSON.stringify(next))
  }

  const handleSelectStrategy = async (name: string) => {
    if (store.isDirty) {
      const ok = await confirm({ title: '未保存的修改', description: '当前策略有未保存的修改，确定要放弃修改并切换吗？', confirmLabel: '放弃并切换' })
      if (!ok) return;
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
    const ok = await confirm({ title: '删除策略', description: `确定要彻底删除策略 ${name} 吗？该操作无法恢复。`, confirmLabel: '永久删除' })
    if (!ok) return;
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

  const handleNewStrategy = async () => {
    if (store.isDirty) {
      const ok = await confirm({ title: '未保存的修改', description: '当前策略有未保存的修改，确定要放弃修改并新建文档吗？', confirmLabel: '放弃并新建' })
      if (!ok) return;
    }
    store.setActiveStrategy('')
    store.setCode('# Draft Strategy...\n')
    store.setLastSavedCode('')
    store.setFormSchema([])
    store.setIsDirty(false)
  }

  // STRAT-07: 从模板新建 (含 BaseStrategy 骨架, 直接通过架构检查)
  const handleUseTemplate = async (tpl: (typeof TEMPLATES)[number]) => {
    if (store.isDirty) {
      const ok = await confirm({ title: '未保存的修改', description: '当前策略有未保存的修改，确定要放弃修改并切换模板吗？', confirmLabel: '放弃并切换' })
      if (!ok) return;
    }
    store.setActiveStrategy('')
    store.setCode(tpl.code)
    store.setLastSavedCode('')
    store.setFormSchema([])
    store.setIsDirty(false)
    toast({ title: `📄 已套用「${tpl.name}」`, description: '模板骨架已生成，可通过架构检查。' })
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
      <Tabs value={sideTab} onValueChange={setSideTab} className="flex flex-col h-full">
        <div className="h-9 px-3 border-b border-border/30 flex items-center justify-between shrink-0 bg-secondary/10">
          <TabsList className="bg-transparent p-0 h-7 gap-0">
            <TabsTrigger value="drafts" className="text-[10px] px-3 h-7 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1">
              <FolderGit2 className="h-3 w-3"/> 草稿库
            </TabsTrigger>
            <TabsTrigger value="versions" className="text-[10px] px-3 h-7 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none flex items-center gap-1">
              <Clock className="h-3 w-3"/> 版本
            </TabsTrigger>
          </TabsList>
          <button onClick={handleNewStrategy} className="text-muted-foreground hover:text-foreground transition-colors" title="新建策略草稿">
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        <TabsContent value="drafts" className="m-0 flex-1 flex flex-col overflow-hidden">
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
                      STATUS_META[s.status]?.cls ?? 'bg-secondary text-muted-foreground'
                    )}>
                      {STATUS_META[s.status]?.label ?? '草稿'}
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

          {/* STRAT-07: 模板中心折叠区 */}
          <div className="shrink-0 border-t border-border/30 bg-secondary/10">
            <button
              onClick={() => setTplOpen(v => !v)}
              className="w-full h-8 px-3 flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground hover:text-foreground transition-colors"
            >
              {tplOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              模板中心
              <span className="ml-auto text-[9px] text-muted-foreground/60 font-normal">新建即带 BaseStrategy 骨架</span>
            </button>
            {tplOpen && (
              <div className="px-2 pb-2 space-y-1.5">
                {TEMPLATES.map((tpl) => (
                  <button
                    key={tpl.id}
                    onClick={() => handleUseTemplate(tpl)}
                    className="w-full text-left rounded-md p-2 bg-secondary/40 border border-border/40 hover:border-primary/40 hover:bg-primary/5 transition-colors group"
                  >
                    <span className="text-[11px] font-semibold text-foreground group-hover:text-primary transition-colors block">{tpl.name}</span>
                    <p className="text-[9px] text-muted-foreground mt-0.5 leading-snug">{tpl.desc}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </TabsContent>

        <TabsContent value="versions" className="m-0 flex-1 overflow-hidden">
          <VersionTimeline />
        </TabsContent>
      </Tabs>
    </div>
  )
}
