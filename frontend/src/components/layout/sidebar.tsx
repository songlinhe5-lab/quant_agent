'use client'

import {
  BarChart3,
  Globe,
  ScanSearch,
  Code2,
  FlaskConical,
  Bot,
  ShieldAlert,
  Brain,
  Settings,
  Server,
} from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface NavModule {
  id: string
  name: string
  label: string
  icon: typeof BarChart3
  domain: 'market' | 'research' | 'trading' | 'risk' | 'system'
  badge?: string
}

const modules: NavModule[] = [
  {
    id: 'quotes',
    name: '行情与高频盘口',
    label: 'Quotes',
    icon: BarChart3,
    domain: 'market',
  },
  {
    id: 'data-center',
    name: '数据中心与宏观',
    label: 'Data Center',
    icon: Globe,
    domain: 'market',
  },
  {
    id: 'screener',
    name: '智能量化选股',
    label: 'Screener',
    icon: ScanSearch,
    domain: 'research',
  },
  {
    id: 'strategy',
    name: '策略研发工作台',
    label: 'Strategy Dev',
    icon: Code2,
    domain: 'research',
  },
  {
    id: 'backtest',
    name: '高频回测引擎',
    label: 'Backtest',
    icon: FlaskConical,
    domain: 'trading',
  },
  {
    id: 'oms',
    name: '订单中枢与算力节点',
    label: 'OMS & Bots',
    icon: Bot,
    domain: 'trading',
    badge: '3',
  },
  {
    id: 'risk',
    name: '资产风控与高级归因',
    label: 'Risk',
    icon: ShieldAlert,
    domain: 'risk',
  },
  {
    id: 'copilot',
    name: 'AI 投研大脑',
    label: 'AI Copilot',
    icon: Brain,
    domain: 'risk',
  },
  {
    id: 'settings',
    name: '系统全局设置',
    label: 'Settings',
    icon: Settings,
    domain: 'system',
  },
  {
    id: 'apm',
    name: '系统性能监控',
    label: 'System APM',
    icon: Server,
    domain: 'system',
  },
]

const domainMeta: Record<string, { label: string; color: string; dot: string }> = {
  market:   { label: '市场感知', color: 'text-sky-600 dark:text-sky-400 transition-colors duration-300',     dot: 'bg-sky-500 dark:bg-sky-400 transition-colors duration-300' },
  research: { label: '投研发现', color: 'text-violet-600 dark:text-violet-400 transition-colors duration-300',  dot: 'bg-violet-500 dark:bg-violet-400 transition-colors duration-300' },
  trading:  { label: '交易执行', color: 'text-emerald-600 dark:text-emerald-400 transition-colors duration-300', dot: 'bg-emerald-500 dark:bg-emerald-400 transition-colors duration-300' },
  risk:     { label: '风控副驾', color: 'text-amber-600 dark:text-amber-400 transition-colors duration-300',   dot: 'bg-amber-500 dark:bg-amber-400 transition-colors duration-300' },
  system:   { label: '系统管理', color: 'text-slate-600 dark:text-slate-400 transition-colors duration-300',   dot: 'bg-slate-500 dark:bg-slate-400 transition-colors duration-300' },
}

const domainOrder = ['market', 'research', 'trading', 'risk', 'system'] as const

interface SidebarProps {
  activeModule: string
  onModuleChange: (moduleId: string) => void
  collapsed?: boolean
}

export function Sidebar({ activeModule, onModuleChange, collapsed = false }: SidebarProps) {
  const grouped = domainOrder.map((domain) => ({
    domain,
    meta: domainMeta[domain],
    items: modules.filter((m) => m.domain === domain),
  }))

  return (
    <aside
      className={cn(
        'flex flex-col border-r border-border/40 bg-slate-50 dark:bg-[oklch(0.10_0.01_270)] transition-all duration-300 overflow-y-auto overflow-x-hidden',
        collapsed ? 'w-14' : 'w-52',
        'h-[calc(100vh-56px)] sticky top-14 z-40'
      )}
      aria-label="模块导航"
    >
      {/* Logo mark when collapsed */}
      {collapsed && (
        <div className="h-10 flex items-center justify-center border-b border-border/30">
          <div className="h-6 w-6 rounded bg-primary/20 flex items-center justify-center">
            <BarChart3 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          </div>
        </div>
      )}

      <nav className="flex-1 py-2">
        <TooltipProvider delayDuration={0}>
        {grouped.map(({ domain, meta, items }, groupIdx) => (
          <div key={domain}>
            {/* Domain separator label */}
            {!collapsed && (
              <div className="flex items-center gap-2 px-3 pt-4 pb-1.5">
                <span className={cn('h-1.5 w-1.5 rounded-full flex-shrink-0', meta.dot)} aria-hidden="true" />
                <span className={cn('text-[10px] font-bold tracking-widest uppercase', meta.color)}>
                  {meta.label}
                </span>
              </div>
            )}
            {collapsed && groupIdx > 0 && (
              <div className="mx-2 my-1 border-t border-border/30" aria-hidden="true" />
            )}

            {/* Module items */}
            <ul className="space-y-0.5 px-1.5">
              {items.map((module) => {
                const Icon = module.icon
                const isActive = activeModule === module.id

                return (
                  <li key={module.id}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          onClick={() => onModuleChange(module.id)}
                          aria-label={module.name}
                          aria-current={isActive ? 'page' : undefined}
                          className={cn(
                            'w-full flex items-center gap-2.5 rounded-md transition-all duration-150 text-left',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                            collapsed ? 'h-9 justify-center px-0' : 'h-8 px-2.5',
                            isActive
                              ? 'bg-primary/15 text-primary border border-primary/30'
                              : 'text-muted-foreground hover:text-foreground hover:bg-secondary/60 border border-transparent'
                          )}
                        >
                          {/* Active accent stripe */}
                          {isActive && !collapsed && (
                            <span className="absolute left-0 w-0.5 h-5 rounded-r-full bg-primary" aria-hidden="true" />
                          )}

                          <Icon
                            className={cn(
                              'flex-shrink-0 transition-colors',
                              collapsed ? 'h-4 w-4' : 'h-3.5 w-3.5',
                              isActive ? 'text-primary' : ''
                            )}
                            aria-hidden="true"
                          />

                          {!collapsed && (
                            <>
                              <span className="flex-1 min-w-0">
                                <span className="block text-xs font-medium truncate leading-none mb-0.5">
                                  {module.label}
                                </span>
                                <span className="block text-[10px] truncate leading-none text-muted-foreground/70">
                                  {module.name}
                                </span>
                              </span>
                              {module.badge && (
                                <span
                                  className="flex-shrink-0 h-4 min-w-[1rem] rounded-full bg-emerald-500/15 dark:bg-emerald-400/20 text-emerald-600 dark:text-emerald-400 transition-colors duration-300 text-[10px] font-bold flex items-center justify-center px-1 tabular-nums"
                                  aria-label={`${module.badge} 个活跃任务`}
                                >
                                  {module.badge}
                                </span>
                              )}
                            </>
                          )}

                          {/* Collapsed badge dot */}
                          {collapsed && module.badge && (
                            <span
                              className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 transition-colors duration-300"
                              aria-label={`${module.badge} 个活跃任务`}
                            />
                          )}
                        </button>
                      </TooltipTrigger>
                      {collapsed && (
                        <TooltipContent side="right" sideOffset={10} className="font-semibold text-xs flex flex-col gap-1">
                          <span>{module.label}</span>
                          <span className="text-[10px] text-muted-foreground font-normal">{module.name}</span>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
        </TooltipProvider>
      </nav>

      {/* Bottom sys info */}
      {!collapsed && (
        <div className="border-t border-border/30 px-3 py-3">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 transition-colors duration-300 status-online" aria-hidden="true" />
            <span className="text-[10px] text-muted-foreground font-mono">LIVE · v2.4.1</span>
          </div>
        </div>
      )}
    </aside>
  )
}
