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
import { TradeHistory } from '@/features/quotes/trade-history'
import { useMarketData } from '@/hooks/use-market-data'
import { WatchlistSidebar } from '@/features/quotes/watchlist-sidebar'
import { LightweightChartCanvas } from '@/features/quotes/lightweight-chart-canvas'
import { ChartErrorBoundary, PanelErrorBoundary } from '@/components/error-boundary'

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
        <LightweightChartCanvas selectedSymbol={compareSymbol} selectedPeriod={comparePeriod} setSelectedPeriod={setComparePeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={false} toggleWatchlist={() => {}} selectedItem={selected} hasData={watchlist.length > 0} syncGroup={syncGroup} />
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
  }, [])

  const { watchlist, addTicker, removeTicker, updateTicker, reorderWatchlist } = useWatchlist()

  const { realQuote, realHistory, setRealHistory, gatewayStatus, isStale, latestStatsRef } = useMarketData({ selectedSymbol, selectedPeriod, watchlist, updateTicker })
  
  // 💡 键盘快捷键支持：使用上下方向键快速切换自选标的，数字键 1-7 快速切换周期
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 如果用户正在输入框中打字，则不拦截键盘事件
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

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
  }, [])
  
  // 🚨 容错处理：当 Watchlist 为空时，提供安全的默认兜底值防止 React 崩溃
  const selected = watchlist.find((w) => w.symbol === selectedSymbol) ?? watchlist[0] ?? {
    symbol: '暂无自选',
    price: 0,
    change: 0,
    vol: '--',
    sparkDir: [0, 0, 0, 0, 0]
  }
  const hasData = watchlist.length > 0

  // 阻止水合期间的渲染，直到客户端获取到真实 Theme 与 LocalStorage 数据
  if (!mounted) return null

  return (
    <div className="relative h-[calc(100vh-80px)] min-h-[600px] w-full bg-background/50 rounded-xl p-1">
      {isStale && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 rounded-xl border border-border/50 shadow-2xl">
          <AlertTriangle className="h-12 w-12 text-amber-500 animate-pulse drop-shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
          <p className="mt-4 text-lg font-bold text-amber-500">数据连接延迟 (STALE)</p>
          <p className="text-sm text-muted-foreground mt-1">行情流可能已过期，正在尝试重新连接...</p>
        </div>
      )}
      
      <PanelGroup direction={isMobile ? "vertical" : "horizontal"} className={cn("h-full w-full gap-2 transition-all duration-300", isStale && "saturate-50 opacity-60")}>
        
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
          {compareMode ? (
            <div className="flex flex-col flex-1 min-h-0 gap-1">
              <div className="flex-1 min-h-0">
                <ChartErrorBoundary name="KlineChart">
                  <LightweightChartCanvas selectedSymbol={selectedSymbol} selectedPeriod={selectedPeriod} setSelectedPeriod={setSelectedPeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={isWatchlistExpanded} toggleWatchlist={toggleWatchlist} selectedItem={selected} hasData={hasData} syncGroup="default" />
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
              <LightweightChartCanvas selectedSymbol={selectedSymbol} selectedPeriod={selectedPeriod} setSelectedPeriod={setSelectedPeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={isWatchlistExpanded} toggleWatchlist={toggleWatchlist} selectedItem={selected} hasData={hasData} syncGroup="default" />
            </ChartErrorBoundary>
          )}
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
                <TabsContent value="dom" className="flex-1 m-0 relative overflow-hidden">
                  <OrderBookWebGL symbol={selectedSymbol} theme={theme} hideHeader />
                </TabsContent>
                <TabsContent value="trades" className="flex-1 m-0 relative flex flex-col bg-background/50">
                  <TradeHistory symbol={selectedSymbol} />
                </TabsContent>
              </Tabs>
            </div>
          ) : (
            <>
              <OrderBookWebGL symbol={selectedSymbol} theme={theme} />
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
    </div>
  )
}
