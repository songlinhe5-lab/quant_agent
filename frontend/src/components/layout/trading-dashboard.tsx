'use client'

import { useState, useCallback, useEffect } from 'react'
import {
  Bell,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  TrendingUp,
  TrendingDown,
  Activity,
  Sun,
  Moon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { Sidebar } from '@/components/layout/sidebar'
import { QuotesModule } from '@/features/trading/quotes'
import { DataCenterModule } from '@/features/trading/data-center'
import { ScreenerModule } from '@/features/trading/screener'
import { StrategyDevModule } from '@/features/trading/strategy'
import { BacktestModule } from '@/features/trading/backtest'
import { OMSModule } from '@/features/trading/oms'
import { RiskModule } from '@/features/trading/risk'
import { CopilotModule } from '@/features/trading/copilot'
import { PerformancePanel } from '@/features/system/performance-panel'
import { ConnectionStatus, AlertBanner } from '@/components/layout/status-indicators'
import { MOCK_HEADER_TICKERS } from '@/services/mock'

type ModuleId =
  | 'quotes'
  | 'data-center'
  | 'screener'
  | 'strategy'
  | 'backtest'
  | 'oms'
  | 'risk'
  | 'copilot'
  | 'settings'
  | 'apm'

const moduleComponents: Record<ModuleId, React.ComponentType> = {
  quotes: QuotesModule,
  'data-center': DataCenterModule,
  screener: ScreenerModule,
  strategy: StrategyDevModule,
  backtest: BacktestModule,
  oms: OMSModule,
  risk: RiskModule,
  copilot: CopilotModule,
  settings: () => <div className="p-10 text-center text-muted-foreground font-mono text-sm">⚙️ 全局设置模块开发中...</div>,
  apm: PerformancePanel,
}

function HeaderTicker() {
  return (
    <div className="hidden lg:flex items-center gap-4 text-xs font-mono">
      {MOCK_HEADER_TICKERS.map((t) => (
        <div key={t.symbol} className="flex items-center gap-1.5">
          <span className="text-muted-foreground">{t.symbol}</span>
          <span className="tabular-nums font-semibold">
            {t.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
          </span>
          <span
            className={cn(
              'tabular-nums flex items-center gap-0.5',
              t.dir > 0 ? 'text-emerald-400' : 'text-red-400'
            )}
          >
            {t.dir > 0 ? (
              <TrendingUp className="h-2.5 w-2.5" aria-hidden="true" />
            ) : (
              <TrendingDown className="h-2.5 w-2.5" aria-hidden="true" />
            )}
            {t.change > 0 ? '+' : ''}{t.change.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  )
}

export function TradingDashboard() {
  const [activeModule, setActiveModule] = useState<ModuleId>('quotes')
  const [isConnected, setIsConnected] = useState(true)
  const [latency, setLatency] = useState(42)
  const [lastUpdate, setLastUpdate] = useState(new Date())
  const [showAlert, setShowAlert] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [isDark, setIsDark] = useState(true)

  // Simulate latency jitter
  useEffect(() => {
    const interval = setInterval(() => {
      setLatency(Math.floor(28 + Math.random() * 60))
      setLastUpdate(new Date())
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  // 获取初始主题状态
  useEffect(() => {
    setIsDark(document.documentElement.classList.contains('dark'))
  }, [])

  const toggleTheme = () => {
    const root = document.documentElement
    const isCurrentlyDark = root.classList.contains('dark')
    
    if (isCurrentlyDark) {
      root.classList.remove('dark')
      localStorage.setItem('quant-theme', 'light')
      setIsDark(false)
    } else {
      root.classList.add('dark')
      localStorage.setItem('quant-theme', 'dark')
      setIsDark(true)
    }
  }

  // 💡 监听 URL Hash 变化，实现跨模块跳转与页面刷新状态保持
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '')
      if (hash && moduleComponents[hash as ModuleId]) {
        setActiveModule(hash as ModuleId)
      }
    }

    if (window.location.hash) handleHashChange()
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  const toggleConnection = useCallback(() => {
    const newState = !isConnected
    setIsConnected(newState)
    if (!newState) setShowAlert(true)
  }, [isConnected])

  const CurrentModuleComponent = moduleComponents[activeModule]

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* ── Top Header ─────────────────────────────────────────────── */}
      <header
        className="glass border-b border-border/40 sticky top-0 z-50 h-14 flex items-center"
        role="banner"
      >
        <div className="flex items-center w-full pr-3 pl-0 gap-3">
          {/* Sidebar toggle + Brand */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              className="hidden lg:flex p-1.5 hover:bg-secondary/70 rounded-md transition-colors"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              title={sidebarCollapsed ? '展开导航栏' : '收起导航栏'}
              aria-label={sidebarCollapsed ? '展开导航栏' : '收起导航栏'}
            >
              {sidebarCollapsed
                ? <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
                : <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
              }
            </button>
            {/* Mobile menu */}
            <button
              className="lg:hidden p-1.5 hover:bg-secondary/70 rounded-md"
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              title="打开导航菜单"
              aria-label="打开导航菜单"
              aria-expanded={isMobileMenuOpen}
            >
              <Activity className="h-4 w-4" aria-hidden="true" />
            </button>

            {/* Logo */}
            <div className="flex items-center gap-1.5">
              <div className="h-6 w-6 rounded bg-primary/20 flex items-center justify-center">
                <Activity className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              </div>
              <span className="font-bold text-sm tracking-tight hidden sm:inline">QuantEdge</span>
              <span className="text-[10px] text-muted-foreground font-mono hidden sm:inline ml-1 border border-border/50 rounded px-1 py-0.5">
                PRO
              </span>
            </div>
          </div>

          {/* Divider */}
          <div className="hidden lg:block h-5 w-px bg-border/50 flex-shrink-0" aria-hidden="true" />

          {/* Live market ticker strip */}
          <div className="flex-1 overflow-hidden">
            <HeaderTicker />
          </div>

          {/* Right actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <ConnectionStatus
              isConnected={isConnected}
              latency={latency}
              lastUpdate={lastUpdate}
              onReconnect={toggleConnection}
            />
            <div className="hidden sm:block h-4 w-px bg-border/50 mx-1" aria-hidden="true" />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={toggleTheme}
              title="切换主题模式"
              aria-label="切换主题模式"
            >
              {isDark ? <Sun className="h-3.5 w-3.5" aria-hidden="true" /> : <Moon className="h-3.5 w-3.5" aria-hidden="true" />}
            </Button>

            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 relative"
              title="系统通知"
              aria-label="查看系统通知"
            >
              <Bell className="h-3.5 w-3.5" aria-hidden="true" />
              {/* Notification dot */}
              <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="系统设置"
              aria-label="打开系统设置"
            >
              <Settings className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </header>

      {/* ── Alert Banner ───────────────────────────────────────────── */}
      {showAlert && !isConnected && (
        <div className="px-4 py-2 z-40">
          <AlertBanner
            type="error"
            message="WebSocket 连接已断开，数据可能已过期。所有价格显示已标注 STALE，请检查网络连接。"
            onDismiss={() => setShowAlert(false)}
          />
        </div>
      )}

      {/* ── Body ───────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        <div className="hidden lg:block flex-shrink-0">
          <Sidebar
            activeModule={activeModule}
            onModuleChange={(id) => {
              setActiveModule(id as ModuleId)
              window.location.hash = id
            }}
            collapsed={sidebarCollapsed}
          />
        </div>

        {/* Mobile sidebar overlay */}
        {isMobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/60 lg:hidden"
            role="dialog"
            aria-modal="true"
            aria-label="导航菜单"
          >
            <div className="absolute left-0 top-0 h-full">
              <Sidebar
                activeModule={activeModule}
                onModuleChange={(id) => {
                  setActiveModule(id as ModuleId)
                  window.location.hash = id
                  setIsMobileMenuOpen(false)
                }}
                collapsed={false}
              />
            </div>
            {/* Click outside to close */}
            <button
              className="absolute inset-0 w-full h-full cursor-default"
              onClick={() => setIsMobileMenuOpen(false)}
              aria-label="关闭菜单"
            />
          </div>
        )}

        {/* Module content area */}
        <main
          className={cn(
            'flex-1 overflow-y-auto',
            !isConnected && 'stale-data'
          )}
          id="main-content"
        >
          <div className="p-4 md:p-5 max-w-full">
            <CurrentModuleComponent />
          </div>
        </main>
      </div>
    </div>
  )
}
