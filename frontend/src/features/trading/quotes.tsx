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

export function QuotesModule() {
  const { theme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const isMobile = useIsMobile()

  // 💡 自选列表展开/收起状态 (持久化到 LocalStorage)
  const [isWatchlistExpanded, setIsWatchlistExpanded] = useState(true)
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
          <LightweightChartCanvas selectedSymbol={selectedSymbol} selectedPeriod={selectedPeriod} setSelectedPeriod={setSelectedPeriod} theme={theme} realQuote={realQuote} realHistory={realHistory} gatewayStatus={gatewayStatus} isWatchlistExpanded={isWatchlistExpanded} toggleWatchlist={toggleWatchlist} selectedItem={selected} hasData={hasData} />
        </Panel>

        <PanelResizeHandle className="w-1 mx-1 rounded-full bg-border/40 hover:bg-primary/50 hover:shadow-[0_0_8px_rgba(var(--primary),0.5)] transition-all cursor-col-resize" />

        {/* ── Right: DOM + Recent Trades ────────────────────────────── */}
        <Panel defaultSize={20} minSize={15} className="flex flex-col gap-2.5">
          
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
        </Panel>
      </PanelGroup>
    </div>
  )
}
