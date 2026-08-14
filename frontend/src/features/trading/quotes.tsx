'use client'

import React, { useState, useEffect } from 'react'
import { ResizablePanelGroup as PanelGroup, ResizablePanel as Panel, ResizableHandle as PanelResizeHandle } from '@/components/ui/resizable'
import { AlertTriangle } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { useWatchlist } from '@/stores/use-watchlist'
import { useMarketStore } from '@/stores/marketStore'
import { useTheme } from 'next-themes'
import { OrderBookWebGL } from '@/features/quotes/order-book-webgl'
import { OrderBookLargeOrderHint } from '@/features/quotes/order-book-large-order-hint'
import { PatternRecognition } from '@/features/quotes/pattern-recognition'
import { TradeHistory } from '@/features/quotes/trade-history'
import { useMarketData } from '@/hooks/use-market-data'
import { WatchlistSidebar } from '@/features/quotes/watchlist-sidebar'
import { LightweightChartCanvas } from '@/features/quotes/lightweight-chart-canvas'
import { ChartErrorBoundary, PanelErrorBoundary } from '@/components/error-boundary'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { AnomalyFlash } from '@/features/quotes/anomaly-flash'
import { NarratorBubble } from '@/features/quotes/narrator-bubble'
import { StrategyIDE } from '@/features/strategy/layout/strategy-ide'
import { MonitorModeLayout } from '@/features/scene/monitor-mode-layout'
import { AIChat } from '@/features/strategy/layout/ai-chat'
import { MarketNewsPanel } from './market-news-panel'

import { InitOverlay, EmptyState } from '@/components/ui/data-display'

// PROD-12: 分屏对比子面板——拥有独立行情数据（独立 WebSocket/历史），并与主图共享同一 syncGroup 实现十字线同步
const COMPARE_PERIODS = [
  { id: '1m', label: '分时' }, { id: '5m', label: '5分' }, { id: '15m', label: '15分' },
  { id: '1h', label: '1时' }, { id: '4h', label: '4时' }, { id: '1d', label: '日K' },
  { id: '1w', label: '周K' }, { id: '1M', label: '月K' },
]

function CompareChartPanel({ watchlist, updateTicker, mainSymbol, theme, syncGroup }: { watchlist: any[]; updateTicker: (s: string, d: any) => void; mainSymbol: string; theme: string | undefined; syncGroup: string }) {
  const [compareSymbol, setCompareSymbol] = useState<string>(() => {
    const others = watchlist.filter((w: any) => w.symbol !== mainSymbol)
    return others[0]?.symbol ?? mainSymbol
  })
  const [comparePeriod, setComparePeriod] = useState<string>('1d')
  const { realQuote, realHistory, gatewayStatus } = useMarketData({ selectedSymbol: compareSymbol, selectedPeriod: comparePeriod, watchlist, updateTicker })
  const selected = watchlist.find((w: any) => w.symbol === compareSymbol) ?? watchlist[0]

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-1 border-b border-border/40 bg-secondary/20 text-[10px] shrink-0">
        <span className="text-muted-foreground font-medium">对比标的</span>
        <select value={compareSymbol} onChange={(e) => setCompareSymbol(e.target.value)} className="bg-card border border-border/50 rounded px-1.5 py-0.5 text-[10px]">
          {watchlist.map((w: any) => <option key={w.symbol} value={w.symbol}>{w.symbol}</option>)}
        </select>
        <span className="text-muted-foreground font-medium ml-2">周期</span>
        <select value={comparePeriod} onChange={(e) => setComparePeriod(e.target.value)} className="bg-card border border-border/50 rounded px-1.5 py-0.5 text-[10px]">
          {COMPARE_PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <span className="text-muted-foreground/70 ml-auto">十字线已与主图同步</span>
      </div>
      <div className="flex-1 min-h-0">
        <AnomalyFlash symbol={compareSymbol} className="h-full">
          <LightweightChartCanvas selectedSymbol={compareSymbol} selectedPeriod={comparePeriod} setSelectedPeriod={setComparePeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={false} toggleWatchlist={() => {}} selectedItem={selected} hasData={watchlist.length > 0} syncGroup={syncGroup} />
          <NarratorBubble symbol={compareSymbol} />
        </AnomalyFlash>
      </div>
    </div>
  )
}

export function QuotesModule() {
  const { theme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const isMobile = useIsMobile()

  // 💡 自选列表展开/收起状态 (持久化到 LocalStorage)
  const [isWatchlistExpanded, setIsWatchlistExpanded] = useState(true)
  // PROD-12: 分屏同步对比模式开关
  const [compareMode, setCompareMode] = useState(false)
  useEffect(() => {
    const saved = localStorage.getItem('quant_watchlist_expanded')
    if (saved !== null) setIsWatchlistExpanded(saved === 'true')
  }, [])
  const toggleWatchlist = () => {
    setIsWatchlistExpanded(prev => {
      const next = !prev; localStorage.setItem('quant_watchlist_expanded', String(next)); return next
    })
  }

  const [selectedSymbol, setSelectedSymbol] = useState('00700.HK')
  const [selectedPeriod, setSelectedPeriod] = useState('1m')  // 💡 默认显示分时图

  useEffect(() => { setMounted(true) }, [])

  const sceneMode = useSceneModeStore((s) => s.mode)
  const isResearchScene = sceneMode === 'research'
  const isMonitorScene = sceneMode === 'monitor'

  // 💡 监听 Zustand 全局 ticker 变化（navbar 搜索跳转）
  const globalTicker = useMarketStore((s: any) => s.currentTicker)
  useEffect(() => {
    if (globalTicker && globalTicker !== selectedSymbol) {
      setSelectedSymbol(globalTicker)
      // 如果标的不在自选列表中，自动添加以确保 WebSocket 订阅和图表展示
      if (!watchlist.some(w => w.symbol === globalTicker)) {
        addTicker(globalTicker)
      }
    }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalTicker])

  // 💡 监听 hash 变化（/market/:ticker 路由重定向触发）
  useEffect(() => {
    const checkTarget = () => {
      const target = sessionStorage.getItem('quant_target_symbol')
      if (target) {
        setSelectedSymbol(target)
        // 自动添加到自选列表
        if (!watchlist.some(w => w.symbol === target)) {
          addTicker(target)
        }
        sessionStorage.removeItem('quant_target_symbol')
      }
    }
    checkTarget()
    window.addEventListener('hashchange', checkTarget)
    return () => window.removeEventListener('hashchange', checkTarget)
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { watchlist, addTicker, removeTicker, updateTicker, reorderWatchlist } = useWatchlist()

  const { realQuote, realHistory, gatewayStatus, isStale, latestStatsRef } = useMarketData({ selectedSymbol, selectedPeriod, watchlist, updateTicker })

  // 💡 键盘快捷键支持：使用上下方向键快速切换自选标的，数字键 1-7 快速切换周期
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 如果用户正在输入框中打字，则不拦截键盘事件
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      // 带修饰键的组合键（如 ⌘1/2/3 研究模式面板跳转）交由对应模式处理，不在此拦截
      if (e.metaKey || e.ctrlKey) return;

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        if (watchlist.length === 0) return;
        const currentIndex = watchlist.findIndex(item => item.symbol === selectedSymbol);

        if (e.key === 'ArrowUp') {
          e.preventDefault(); // 防止页面滚动
          if (currentIndex > 0) setSelectedSymbol(watchlist[currentIndex - 1].symbol);
        } else if (e.key === 'ArrowDown') {
          e.preventDefault(); // 防止页面滚动
          if (currentIndex >= 0 && currentIndex < watchlist.length - 1) {
            setSelectedSymbol(watchlist[currentIndex + 1].symbol);
          } else if (currentIndex === -1) {
            setSelectedSymbol(watchlist[0].symbol); // 兜底选中第一个
          }
        }
      }

      // 💡 数字键 1-6 快速切换 K 线周期
      const periodMap: Record<string, string> = {
        '1': '1m',   // 分时
        '2': 'tick', // Tick
        '3': '5m',   // 5日
        '4': '1d',   // 日K
        '5': '1w',   // 周K
        '6': '1M',   // 月K
      };
      if (periodMap[e.key]) {
        e.preventDefault();
        setSelectedPeriod(periodMap[e.key]);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const hasData = watchlist.length > 0
  // §14.1：watchlist 为空时不再注入内联假对象（避免 PROD 下出现假数据占位），
  // 回落 undefined，由下方图表区 EmptyState 提示用户添加标的。
  const selected = hasData ? (watchlist.find((w) => w.symbol === selectedSymbol) ?? watchlist[0]) : undefined

  // §14.2：初始化态给出可见反馈（骨架屏），禁止静默白屏或卡死
  if (!mounted) {
    return <InitOverlay variant="skeleton" label="正在初始化行情终端…" className="h-[calc(100vh-80px)] min-h-[600px]" />
  }

  // PROD-04e: 研究模式专属布局 —— 多面板拖拽（代码/回测/AI）+ 底部 Terminal + ⌘1/2/3 快捷键
  if (isResearchScene) {
    return <StrategyIDE className="h-[calc(100vh-80px)]" />
  }

  // PROD-04f: 监控模式专属布局 —— 告警流主视图 + Bot 状态矩阵 + 风控仪表盘
  if (isMonitorScene) {
    return <MonitorModeLayout />
  }

  // 注：原 PROD-04a「盯盘模式全屏 K线 + 悬浮球自选」布局因 FloatingWatchlist 悬浮球被顶部导航栏
  // 遮挡导致自选列表无法打开、全屏容器内 K 线高度塌陷导致拉不到数据，已弃用。
  // 现 watch 场景回落到下方经充分验证的标准三栏布局（WatchlistSidebar + 主图 K线 + 盘口），
  // 同时保留 monitor / research 的专属布局。WatchScene 仅作为场景标识用于密度/AI 角色切换。

  return (
    <div className="resp-auto-panels resp-3col relative flex h-[calc(100vh-80px)] min-h-[600px] w-full bg-background/50 rounded-xl p-1">
      {isStale && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 rounded-xl border border-border/50 shadow-2xl">
          <AlertTriangle className="h-12 w-12 text-amber-500 animate-pulse drop-shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
          <p className="mt-4 text-lg font-bold text-amber-500">数据连接延迟 (STALE)</p>
          <p className="text-sm text-muted-foreground mt-1">行情流可能已过期，正在尝试重新连接...</p>
        </div>
      )}

      <PatternRecognition symbol={selectedSymbol} history={realHistory} />

      <PanelGroup direction={isMobile ? "vertical" : "horizontal"} className={cn("flex-1 min-w-0 h-full gap-2 transition-all duration-300", isStale && "saturate-50 opacity-60")}>

        {/* ── Left: Watchlist ──────────────────────────── */}
        {isWatchlistExpanded && (
          <>
            <WatchlistSidebar watchlist={watchlist} selectedSymbol={selectedSymbol} setSelectedSymbol={setSelectedSymbol} theme={theme} toggleWatchlist={toggleWatchlist} addTicker={addTicker} removeTicker={removeTicker} reorderWatchlist={reorderWatchlist} latestStatsRef={latestStatsRef} />
            <PanelResizeHandle className="w-1 mx-1 rounded-full bg-border/40 hover:bg-primary/50 hover:shadow-[0_0_8px_rgba(var(--primary),0.5)] transition-all cursor-col-resize" />
          </>
        )}

        {/* ── Middle: Chart (Main Focus) ───────────────────────── */}
        <Panel defaultSize={60} minSize={40} className="flex flex-col">
          <div className="flex items-center justify-between px-3 py-1 border-b border-border/40 bg-secondary/10 shrink-0">
            <span className="text-[10px] font-medium text-muted-foreground">主图</span>
            <button
              onClick={() => setCompareMode(!compareMode)}
              className={cn("text-[10px] px-2 py-0.5 rounded border border-border/50 transition-colors", compareMode ? "bg-primary/20 text-primary" : "bg-background hover:bg-secondary text-muted-foreground")}
            >
              {compareMode ? '退出同步对比' : '同步对比'}
            </button>
          </div>
          {/* AI-01: 默认/研究三栏场景也挂载异动解说联动——与 compare/watch 场景一致 */}
          <AnomalyFlash symbol={selectedSymbol}>
            {hasData ? (
              compareMode ? (
                <div className="flex flex-col flex-1 min-h-0 gap-1">
                  <div className="flex-1 min-h-0">
                    <ChartErrorBoundary name="KlineChart">
                      <LightweightChartCanvas selectedSymbol={selectedSymbol} selectedPeriod={selectedPeriod} setSelectedPeriod={setSelectedPeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={isWatchlistExpanded} toggleWatchlist={toggleWatchlist} selectedItem={selected!} hasData={hasData} syncGroup="default" />
                    </ChartErrorBoundary>
                  </div>
                  <div className="flex-1 min-h-0 border-t border-border/40">
                    <ChartErrorBoundary name="KlineChartCompare">
                      <CompareChartPanel watchlist={watchlist} updateTicker={updateTicker} mainSymbol={selectedSymbol} theme={theme} syncGroup="default" />
                    </ChartErrorBoundary>
                  </div>
                </div>
              ) : (
                <ChartErrorBoundary name="KlineChart">
                  <LightweightChartCanvas selectedSymbol={selectedSymbol} selectedPeriod={selectedPeriod} setSelectedPeriod={setSelectedPeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={isWatchlistExpanded} toggleWatchlist={toggleWatchlist} selectedItem={selected!} hasData={hasData} syncGroup="default" />
                </ChartErrorBoundary>
              )
            ) : (
              <EmptyState title="暂无自选标的" description="添加关注标的即可开始盯盘，行情订阅建立后将自动加载。" action={<button type="button" onClick={() => addTicker(selectedSymbol)} className="rounded-md border border-border/40 px-3 py-1.5 text-sm text-foreground/80 transition-colors hover:border-border/70 hover:text-foreground">添加 {selectedSymbol}</button>} />
            )}
            <NarratorBubble symbol={selectedSymbol} />
          </AnomalyFlash>
        </Panel>

        <PanelResizeHandle className="w-1 mx-1 rounded-full bg-border/40 hover:bg-primary/50 hover:shadow-[0_0_8px_rgba(var(--primary),0.5)] transition-all cursor-col-resize" />

        {/* ── Right: DOM + Recent Trades ────────────────────────────── */}
        <Panel defaultSize={20} minSize={15} className="flex flex-col gap-2.5">
          <PanelErrorBoundary name="OrderBookPanel">
          {isMobile ? (
            <div className="glass-card rounded-xl overflow-hidden flex flex-col h-full shadow-sm border-border/40">
              <Tabs defaultValue="dom" className="flex flex-col h-full">
                <div className="border-b border-border/40 bg-secondary/20 px-3 pt-1.5 flex items-center shrink-0">
                  <TabsList className="bg-transparent p-0 gap-0 h-8">
                    <TabsTrigger value="dom" className="text-[11px] px-3 h-8 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">
                      订单簿 DOM
                    </TabsTrigger>
                    <TabsTrigger value="trades" className="text-[11px] px-3 h-8 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent">
                      成交流水
                    </TabsTrigger>
                  </TabsList>
                </div>
                <TabsContent value="dom" className="flex-1 m-0 relative overflow-hidden flex flex-col">
                  <OrderBookWebGL symbol={selectedSymbol} theme={theme} hideHeader />
                  <OrderBookLargeOrderHint symbol={selectedSymbol} />
                </TabsContent>
                <TabsContent value="trades" className="flex-1 m-0 relative flex flex-col bg-background/50">
                  <TradeHistory symbol={selectedSymbol} />
                </TabsContent>
              </Tabs>
            </div>
          ) : (
            <>
              <OrderBookWebGL symbol={selectedSymbol} theme={theme} />
              <OrderBookLargeOrderHint symbol={selectedSymbol} />
              <div className="glass-card rounded-xl overflow-hidden flex flex-col flex-1 shadow-sm border-border/40">
                <div className="px-3 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase">成交流水</span>
                </div>
                <TradeHistory symbol={selectedSymbol} />
              </div>
            </>
          )}
          </PanelErrorBoundary>
        </Panel>
      </PanelGroup>

      {/* PROD-05 深化：1920px 自动展开「新闻流」次面板（默认隐藏，≥1920px 由 .resp-auto-panels 揭示） */}
      <div data-secondary-panel className="hidden w-[340px] flex-shrink-0 min-h-0 border-l border-border/40">
        <MarketNewsPanel />
      </div>

      {/* PROD-05 深化：超宽屏 21:9 三栏之一（行情+策略/新闻+AI），≥2560px 由 .resp-3col 揭示 */}
      <div data-ultrawide-ai className="hidden w-[360px] flex-shrink-0 min-h-0 border-l border-border/40">
        <AIChat />
      </div>
    </div>
  )
}
