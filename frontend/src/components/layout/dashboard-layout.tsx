import React, { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { KeepAliveOutlet } from './keep-alive-outlet'
import { Globe, BarChart3, ScanSearch, Code2, FlaskConical, Bot, ShieldAlert, Server, Bell, Database, Users, Microscope } from 'lucide-react'
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
import { registerNavigate } from '@/lib/navigate'
import { Navbar } from './navbar'
import { StatusBar } from './status-bar'
import { TradingModeBanner } from './trading-mode-banner'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { useChat } from '@/features/copilot/useChat'
import { GlobalSettingsDrawer } from '@/features/settings/settings-drawer'
import { BackendStatusBanner } from './backend-status-banner'
import { GlobalAlertGateway } from '@/features/alert/global-alert-gateway'
import { hydrateTradingMode } from '@/features/trading/trading-mode-actions'
import { MobileTabBar } from '@/components/layout/mobile-tab-bar'
import { DebugLogPanel } from '@/components/debug/debug-log-panel'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { SCENE_META } from '@/features/scene/scene-mode-types'
import { useSceneHotkey } from '@/features/scene/use-scene-hotkey'
import { FullscreenCopilot } from '@/features/scene/fullscreen-copilot'

const domainMeta: Record<string, { label: string; color: string; dot: string }> = {
  market:   { label: '市场感知', color: 'text-sky-600 dark:text-sky-400',     dot: 'bg-sky-500 dark:bg-sky-400' },
  research: { label: '投研发现', color: 'text-violet-600 dark:text-violet-400',  dot: 'bg-violet-500 dark:bg-violet-400' },
  trading:  { label: '交易执行', color: 'text-emerald-600 dark:text-emerald-400', dot: 'bg-emerald-500 dark:bg-emerald-400' },
  risk:     { label: '风控副驾', color: 'text-amber-600 dark:text-amber-400',   dot: 'bg-amber-500 dark:bg-amber-400' },
  system:   { label: '系统管理', color: 'text-slate-600 dark:text-slate-400',   dot: 'bg-slate-500 dark:bg-slate-400' },
}

const domainOrder = ['market', 'research', 'trading', 'risk', 'system'] as const

type NavItem = {
  url: string
  name: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  domain: string
  badge?: string
  /** drawer：侧栏点开全局抽屉，不导航 */
  action?: 'copilot' | 'settings'
}

const modules: NavItem[] = [
  { url: '/data-center', name: '数据中心与宏观', label: 'Data Center', icon: Globe, domain: 'market' },
  { url: '/quotes', name: '行情与高频盘口', label: 'Quotes', icon: BarChart3, domain: 'market' },
  { url: '/screener', name: '智能量化选股', label: 'Screener', icon: ScanSearch, domain: 'research' },
  { url: '/strategy', name: '策略研发工作台', label: 'Strategy Dev', icon: Code2, domain: 'research' },
  { url: '/research', name: '投研工作台', label: 'Research', icon: Microscope, domain: 'research' },
  { url: '/research-team', name: '专家团投研会', label: 'Research Team', icon: Users, domain: 'research' },
  { url: '/backtest', name: '高频回测引擎', label: 'Backtest', icon: FlaskConical, domain: 'trading' },
  { url: '/oms', name: '订单中枢与算力节点', label: 'OMS & Bots', icon: Bot, domain: 'trading', badge: '3' },
  { url: '/risk', name: '资产风控与高级归因', label: 'Risk', icon: ShieldAlert, domain: 'risk' },
  { url: '/alerts', name: '告警中心与推送', label: 'Alert Center', icon: Bell, domain: 'risk' },
  { url: '/apm', name: '系统性能监控', label: 'System APM', icon: Server, domain: 'system' },
  { url: '/datasource-health', name: '数据源健康看板', label: 'Data Sources', icon: Database, domain: 'system' },
]

function useCopilotHotkey() {
  const navigate = useNavigate()

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return
      if (e.key.toLowerCase() !== 'a') return
      e.preventDefault()
      // UI 拆分：AI Copilot 已迁至左侧「投研」分栏，快捷键直接前往 /research
      navigate('/research')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate])
}

/**
 * 导航桥：把 useNavigate 注入全局，供 store/context 在任意位置调用 navigate()。
 * 挂在主布局内，保证每次路由可用。
 */
function NavigationBridge() {
  const navigate = useNavigate()
  useEffect(() => {
    registerNavigate(navigate)
  }, [navigate])
  return null
}

/** 常驻聊天运行时：初始化 SSE 编排 + 注入 handleSend + 监听跨模块 invoke。
 *  UI 拆分后抽屉被隐藏，但 AI 对话已迁移至左侧「投研」分栏，
 *  此运行时在布局层常驻，确保投研页/全屏 AI 的会话逻辑可用（逻辑复用）。 */
function ChatRuntime() {
  useChat()
  return null
}

// UIRF-23: OMS 徽章动态计数（活跃订单数 + 运行 bots 数），替换硬编码 badge:'3'
function useOmsBadge(): string | null {
  const [badge, setBadge] = useState<string | null>(null)
  useEffect(() => {
    let mounted = true
    // UIRF-23: 后端 OMS 初始状态接口实为 /oms/state（后端无 /oms/initial-state，旧路径会 404）
    apiClient.get('/oms/state')
      .then((res: any) => {
        if (!mounted) return
        const data = res?.data?.data
        if (!data) return
        const activeOrders = Array.isArray(data.active_orders) ? data.active_orders.length : 0
        const runningBots = Array.isArray(data.bots)
          ? data.bots.filter((b: any) => b.status === 'running' || b.status === 'active').length
          : 0
        const count = activeOrders + runningBots
        setBadge(count > 0 ? String(count) : null)
      })
      .catch(() => { /* 忽略，保持无徽章 */ })
    return () => { mounted = false }
  }, [])
  return badge
}

function useHydrateTradingMode() {
  useEffect(() => {
    void hydrateTradingMode()
  }, [])
}

/** PROD-04: 研究模式自动前往左侧「投研」分栏（AI 副驾已内嵌）；AI 分析模式由布局渲染全屏 */
function useSceneAiBehavior() {
  const sceneMode = useSceneModeStore((s) => s.mode)
  const navigate = useNavigate()

  useEffect(() => {
    const meta = SCENE_META[sceneMode]
    if (meta.aiRole === 'drawer') {
      // UI 拆分：抽屉已隐藏，研究场景直接前往左侧投研分栏
      navigate('/research')
    }
    // fullscreen：由布局 isAiFullscreen 分支渲染，无需额外跳转
  }, [sceneMode, navigate])
}

export default function DashboardLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const pathname = location.pathname
  const settingsOpen = useLayoutStore((s) => s.settingsOpen)
  const openSettings = useLayoutStore((s) => s.openSettings)
  const sceneMode = useSceneModeStore((s) => s.mode)
  const sceneMeta = SCENE_META[sceneMode]

  useCopilotHotkey()
  useSceneHotkey()
  useHydrateTradingMode()
  useSceneAiBehavior()
  // UIRF-23: OMS 徽章动态计数（活跃订单 + 运行 bots）
  const omsBadge = useOmsBadge()

  const isAiFullscreen = sceneMeta.aiRole === 'fullscreen'
  const sidebarHidden = !sceneMeta.sidebarVisible

  return (
    <div data-scene-mode={sceneMode} className="h-screen overflow-hidden">
    <SidebarProvider className="h-full overflow-hidden">
      {/* FE-15: 桌面侧栏；<768 由 MobileTabBar 接管；PROD-04: 盯盘/AI分析模式隐藏 */}
      <Sidebar className={cn(
        'hidden md:flex border-r border-border/40 md:!top-14 md:!h-[calc(100svh-3.5rem)]',
        sidebarHidden && 'md:!hidden',
      )} style={{ width: '16rem' } as React.CSSProperties}>
        <SidebarContent>
          {domainOrder.map((domain) => {
            const items = modules.filter((m) => m.domain === domain)
              // UIRF-23: OMS 徽章动态计数覆盖静态 badge
              .map((m) => (m.url === '/oms' ? { ...m, badge: omsBadge ?? m.badge } : m))
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
                      // 前缀冲突规避：/research 需精确匹配，避免吞掉 /research-team 的高亮
                      const routeActive = item.url === '/'
                        ? pathname === '/'
                        : item.url === '/research'
                          ? (pathname === '/research' || pathname.startsWith('/research/'))
                          : pathname.startsWith(item.url)
                      const drawerActive =
                        item.action === 'settings' && settingsOpen
                      const isActive = item.action ? drawerActive || routeActive : routeActive

                      return (
                        <SidebarMenuItem key={item.url}>
                          {item.action ? (
                            <SidebarMenuButton
                              isActive={isActive}
                              tooltip={item.name}
                              className="h-[42px] transition-all duration-300 hover:bg-primary/10 data-[active=true]:bg-primary/15 data-[active=true]:text-primary data-[active=true]:font-bold relative"
                              onClick={() => {
                                if (item.action === 'copilot') navigate('/research')
                                else openSettings()
                              }}
                            >
                              {isActive && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-primary" aria-hidden="true" />}
                              <item.icon className="h-[18px] w-[18px] shrink-0" />
                              <div className="flex-1 flex flex-col min-w-0 overflow-hidden group-data-[collapsible=icon]:hidden text-left">
                                <span className="text-[13px] font-semibold leading-tight truncate mb-0.5">{item.label}</span>
                                <span className="text-[10px] text-muted-foreground leading-none truncate font-normal">{item.name}</span>
                              </div>
                            </SidebarMenuButton>
                          ) : (
                            <SidebarMenuButton asChild isActive={isActive} tooltip={item.name} className="h-[42px] transition-all duration-300 hover:bg-primary/10 data-[active=true]:bg-primary/15 data-[active=true]:text-primary data-[active=true]:font-bold relative">
                              <Link to={item.url} className="flex items-center w-full gap-2">
                                {isActive && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-primary" aria-hidden="true" />}
                                <item.icon className="h-[18px] w-[18px] shrink-0" />
                                <div className="flex-1 flex flex-col min-w-0 overflow-hidden group-data-[collapsible=icon]:hidden">
                                  <span className="text-[13px] font-semibold leading-tight truncate mb-0.5">{item.label}</span>
                                  <span className="text-[10px] text-muted-foreground leading-none truncate font-normal">{item.name}</span>
                                </div>
                                {item.badge && (
                                  <span className="ml-auto shrink-0 h-4 min-w-[1rem] rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 text-[9px] font-bold flex items-center justify-center px-1 tabular-nums group-data-[collapsible=icon]:hidden transition-colors duration-300">
                                    {item.badge}
                                  </span>
                                )}
                                {item.badge && (
                                  <span className="absolute top-2 right-2 h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 hidden group-data-[collapsible=icon]:block transition-colors duration-300" aria-label={`${item.badge} notifications`} />
                                )}
                              </Link>
                            </SidebarMenuButton>
                          )}
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

      <SidebarInset className={cn(
        'h-full min-h-0 overflow-hidden bg-background',
        sidebarHidden ? 'md:ml-0' : 'md:ml-[16rem] peer-data-[state=collapsed]:md:ml-[3rem]',
      )}>
        <Navbar />
        <BackendStatusBanner />
        <TradingModeBanner />
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* PROD-04: AI 分析模式渲染全屏对话工作台 */}
          {isAiFullscreen ? (
            <main className="flex-1 min-w-0 overflow-hidden">
              <FullscreenCopilot />
            </main>
          ) : (
            <>
              {/* FE-29: desktop/wide/ultrawide 内容区；移动端预留 Tab Bar */}
              <main
                className="flex-1 min-w-0 p-3 md:p-4 pb-16 md:pb-4 overflow-y-auto desktop:max-w-none wide:px-6 ultrawide:px-8"
                style={{ fontSize: `calc(14px * var(--density-scale, 1))` }}
              >
                <KeepAliveOutlet />
              </main>
            </>
          )}
        </div>
        {/* FE-DEBUG-01: 底部实时日志 DEBUG 面板（主服务 + 各数据子服务，高度可拖 ≤1/3 屏） */}
        <DebugLogPanel />
        <div className="hidden md:block">
          <StatusBar />
        </div>
        <MobileTabBar />
        <GlobalSettingsDrawer />
        <GlobalAlertGateway />
      </SidebarInset>

      {/* 全局导航桥；常驻聊天运行时（UI 拆分后抽屉隐藏，聊天逻辑复用）。
          AI 分析全屏模式由 FullscreenCopilot 自身挂载 useChat，此处跳过避免双重初始化。 */}
      <NavigationBridge />
      {!isAiFullscreen && <ChatRuntime />}
    </SidebarProvider>
    </div>
  )
}
