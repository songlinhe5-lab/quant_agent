import React from 'react'
import { Link, useLocation, Outlet } from 'react-router-dom'
import { Globe, BarChart3, ScanSearch, Code2, FlaskConical, Bot, ShieldAlert, Brain, Settings, Server } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarInset,
} from '@/components/ui/sidebar'
import { cn } from '@/lib/utils'
import { Navbar } from './navbar'
import { WsStatusIndicator } from './ws-status-indicator'

const domainMeta: Record<string, { label: string; color: string; dot: string }> = {
  market:   { label: '市场感知', color: 'text-sky-600 dark:text-sky-400',     dot: 'bg-sky-500 dark:bg-sky-400' },
  research: { label: '投研发现', color: 'text-violet-600 dark:text-violet-400',  dot: 'bg-violet-500 dark:bg-violet-400' },
  trading:  { label: '交易执行', color: 'text-emerald-600 dark:text-emerald-400', dot: 'bg-emerald-500 dark:bg-emerald-400' },
  risk:     { label: '风控副驾', color: 'text-amber-600 dark:text-amber-400',   dot: 'bg-amber-500 dark:bg-amber-400' },
  system:   { label: '系统管理', color: 'text-slate-600 dark:text-slate-400',   dot: 'bg-slate-500 dark:bg-slate-400' },
}

const domainOrder = ['market', 'research', 'trading', 'risk', 'system'] as const

const modules = [
  { url: '/data-center', name: '数据中心与宏观', label: 'Data Center', icon: Globe, domain: 'market' },
  { url: '/quotes', name: '行情与高频盘口', label: 'Quotes', icon: BarChart3, domain: 'market' },
  { url: '/screener', name: '智能量化选股', label: 'Screener', icon: ScanSearch, domain: 'research' },
  { url: '/strategy', name: '策略研发工作台', label: 'Strategy Dev', icon: Code2, domain: 'research' },
  { url: '/backtest', name: '高频回测引擎', label: 'Backtest', icon: FlaskConical, domain: 'trading' },
  { url: '/oms', name: '订单中枢与算力节点', label: 'OMS & Bots', icon: Bot, domain: 'trading', badge: '3' },
  { url: '/risk', name: '资产风控与高级归因', label: 'Risk', icon: ShieldAlert, domain: 'risk' },
  { url: '/copilot', name: 'AI 投研大脑', label: 'AI Copilot', icon: Brain, domain: 'risk' },
  { url: '/settings', name: '系统全局设置', label: 'Settings', icon: Settings, domain: 'system' },
  { url: '/apm', name: '系统性能监控', label: 'System APM', icon: Server, domain: 'system' },
]

export default function DashboardLayout() {
  const location = useLocation();
  const pathname = location.pathname;

  return (
    <SidebarProvider className="flex-col h-screen overflow-hidden">
      {/* 顶部全局导航栏横跨 100% 宽度 */}
      <Navbar />

      <div className="flex flex-1 overflow-hidden w-full relative">
      {/* 侧边栏主体 */}
      <Sidebar className="border-r border-border/40 md:!top-14 md:!h-[calc(100svh-56px)]">
        <SidebarContent>
          {domainOrder.map((domain) => {
            const items = modules.filter((m) => m.domain === domain)
            if (items.length === 0) return null
            const meta = domainMeta[domain]

            return (
              <SidebarGroup key={domain} className="py-1">
                  <SidebarGroupLabel className="flex items-center gap-2 px-3 text-sidebar-foreground/70">
                    <span className={cn('h-1.5 w-1.5 rounded-full flex-shrink-0 transition-colors duration-300', meta.dot)} aria-hidden="true" />
                    <span className={cn('text-[10px] font-bold tracking-widest uppercase transition-colors duration-300', meta.color)}>
                      {meta.label}
                    </span>
                  </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {items.map((item) => {
                      const isActive = item.url === '/' ? pathname === '/' : pathname.startsWith(item.url)
                      return (
                        <SidebarMenuItem key={item.url}>
                          <SidebarMenuButton asChild isActive={isActive} tooltip={item.name} className="h-[42px] transition-all duration-300 hover:bg-primary/10 data-[active=true]:bg-primary/15 data-[active=true]:text-primary data-[active=true]:font-bold relative">
                            <Link to={item.url} className="flex items-center w-full gap-2">
                              {/* 侧边活动状态指示条 */}
                              {isActive && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-primary" aria-hidden="true" />}
                              <item.icon className="h-[18px] w-[18px] shrink-0" />
                              <div className="flex-1 flex flex-col min-w-0 overflow-hidden group-data-[collapsible=icon]:hidden">
                                <span className="text-[13px] font-semibold leading-tight truncate mb-0.5">{item.label}</span>
                                <span className="text-[10px] text-muted-foreground leading-none truncate font-normal">{item.name}</span>
                              </div>
                              {/* 展开状态的 Badge */}
                              {item.badge && (
                                <span className="ml-auto shrink-0 h-4 min-w-[1rem] rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 text-[9px] font-bold flex items-center justify-center px-1 tabular-nums group-data-[collapsible=icon]:hidden transition-colors duration-300">
                                  {item.badge}
                                </span>
                              )}
                              {/* 折叠状态的 Badge 提示点 */}
                              {item.badge && (
                                <span className="absolute top-2 right-2 h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 hidden group-data-[collapsible=icon]:block transition-colors duration-300" aria-label={`${item.badge} notifications`} />
                              )}
                            </Link>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      )
                    })}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            )
          })}
        </SidebarContent>
      </Sidebar>

      </div>

      {/* 右侧主内容区域 */}
      <SidebarInset className="flex-1 h-full min-h-0 overflow-hidden bg-background">
        <main className="flex-1 p-4 overflow-y-auto">
          <Outlet />
        </main>
        <WsStatusIndicator />
      </SidebarInset>
    </SidebarProvider>
  )
}
