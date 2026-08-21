'use client'

import React, { useState, useEffect } from 'react'
import { ResizablePanelGroup as PanelGroup, ResizablePanel as Panel, ResizableHandle as PanelResizeHandle } from '@/components/ui/resizable'
import { AlertTriangle } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { useWatchlist } from '@/stores/use-watchlist'
import { useMarketStore } from '@/stores/marketStore'
import { useTheme } from 'next-themes'
import { OrderBookWebGL } from '@/features/quotes/order-book-webgl'
import { OrderBookDepthPanel } from '@/features/quotes/order-book-depth-panel'
import { BrokerPanel } from '@/features/quotes/broker-panel'
import { OrderBookLargeOrderHint } from '@/features/quotes/order-book-large-order-hint'
import { PatternRecognition } from '@/features/quotes/pattern-recognition'
import { TradeHistory } from '@/features/quotes/trade-history'
import { useMarketData } from '@/hooks/use-market-data'
import { WatchlistSidebar } from '@/features/quotes/watchlist-sidebar'
import { LightweightChartCanvas } from '@/features/quotes/lightweight-chart-canvas'
import { ChartErrorBoundary, PanelErrorBoundary } from '@/components/error-boundary'
import { AnomalyFlash } from '@/features/quotes/anomaly-flash'
import { NarratorBubble } from '@/features/quotes/narrator-bubble'
import { CompareChartPanel } from '@/features/quotes/compare-chart-panel'
import { AIChat } from '@/features/strategy/layout/ai-chat'
import { MicroPanel } from '@/features/quotes/micro-panel'
import { OptionModePanel } from '@/features/quotes/option-mode-panel'
import { MarketClocks } from '@/features/data-center/shared'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { SCENE_META } from '@/features/scene/scene-mode-types'

import { InitOverlay, EmptyState } from '@/components/ui/data-display'

// 💡 标的视图偏好持久化：按 symbol 存 { period, chartMode, rightMode } 到 localStorage，进入工作台时自动恢复
const VIEWPREF_KEY = 'quant_symbol_viewpref'
type SymbolViewPref = { period: string; chartMode: 'chart' | 'options'; rightMode: 'dom' | 'micro' }
const readViewPrefs = (): Record<string, SymbolViewPref> => {
  try { return JSON.parse(localStorage.getItem(VIEWPREF_KEY) || '{}') } catch { return {} }
}
const writeViewPrefs = (m: Record<string, SymbolViewPref>) => localStorage.setItem(VIEWPREF_KEY, JSON.stringify(m))
const PERIOD_LABEL: Record<string, string> = {
  '1m': '分时', '5m': '5日', '15m': '15分', '1h': '1时', '4h': '4时', '1d': '日K', '1w': '周K', '1M': '月K', '1q': '季K', '1y': '年K',
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
  // 💡 进入工作台时按当前标的自动恢复已保存的视图偏好
  const initialPref = readViewPrefs()['00700.HK']
  const [selectedPeriod, setSelectedPeriod] = useState<string>(initialPref?.period ?? '1m')  // 💡 默认显示分时图
  // FE-26：中列 [K 线 | 期权] 模式切换（Figma Frame 5）
  const [chartMode, setChartMode] = useState<'chart' | 'options'>(initialPref?.chartMode ?? 'chart')
  // FE-26：右栏 [盘口 | 微观 | 选择持久化] 模式切换（Figma Frame 4 / 第三个 tab）
  const [rightMode, setRightMode] = useState<'dom' | 'micro' | 'persist'>(initialPref?.rightMode ?? 'dom')
  // 💡 已保存的全部标的视图偏好（localStorage 镜像）
  const [savedPrefs, setSavedPrefs] = useState<Record<string, SymbolViewPref>>(readViewPrefs())

  // UIRF-20 深化：从 Store 读取场景模式并监听变化
  const currentScene = useSceneModeStore((s) => s.mode)

  useEffect(() => { setMounted(true) }, [])

  // UIRF-20 深化：不同场景下自动切换到对应的 Tab
  // watch → DOM (盘口), research → Micro (微观)
  useEffect(() => {
    // 仅在非 persist 模式下才自动切换
    if (rightMode === 'persist') return

    // 盯盘模式 → 默认盘口
    if (currentScene === 'watch' && rightMode !== 'dom') {
      setRightMode('dom')
    }
    // 研究模式 → 默认微观
    else if (currentScene === 'research' && rightMode !== 'micro') {
      setRightMode('micro')
    }
  }, [currentScene, rightMode])

  // 💡 切换标的/周期/图表模式/右栏时自动持久化当前标的视图偏好
  useEffect(() => {
    setSavedPrefs((prev) => {
      const next = { ...prev, [selectedSymbol]: { period: selectedPeriod, chartMode, rightMode: rightMode === 'persist' ? 'micro' : rightMode } as SymbolViewPref }
      writeViewPrefs(next)
      return next
    })
  }, [selectedSymbol, selectedPeriod, chartMode, rightMode])

  // 🛠️ 2026-08-14：Quotes（行情页）不再被 research/monitor 场景劫持替换布局。
  // 场景模式（watch/research/monitor）改为导航栏场景切换器的「独立入口」：
  // watch→/quotes, research→/strategy, monitor→/monitor, ai-analysis→/copilot。
  // Quotes 模块永远渲染标准三栏行情布局（自选列表 + 主图 K线 + 盘口），
  // 保证盯盘/Quotes 页始终能看到行情 K 线，不被监控总览/研究 IDE 顶替。

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

  // 💡 初始化兜底：直接打开 /quotes 页（无任何搜索/路由跳转）时 watchlist 默认空，
  // 会导致 useMarketData 内 `if (watchlist.length === 0) return` 不建 WS / 不拉 K 线。
  // 此处把当前 selectedSymbol 自动加进自选，保证首屏即有实时行情与盘口。
  useEffect(() => {
    if (watchlist.length === 0 && selectedSymbol) {
      addTicker(selectedSymbol)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { realQuote, realHistory, gatewayStatus, isStale, latestStatsRef } = useMarketData({ selectedSymbol, selectedPeriod, watchlist, updateTicker })

  // 💡 键盘快捷键支持：使用上下方向键快速切换自选标的，数字键 1-7 快速切换周期
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 如果用户正在输入框中打字，则不拦截键盘事件
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      // 带修饰键的组合键（如 ⌘1/2/3 研究模式面板跳转）交由对应模式处理，不在此拦截
      if (e.metaKey || e.ctrlKey) return;

      // UIRF-20: 个股工作台快捷鍵 D/M/C/O
      // D: DOM(盘口), M: Micro(微观), C: Chart(K 线), O: Options(期权)
      if (!e.altKey) {
        // 無 Alt 時，優先級低於以下操作
      } else {
        // Alt+D → 切換盤口 (DOM)
        if (e.key.toLowerCase() === 'd' && rightMode !== 'dom') {
          e.preventDefault();
          setRightMode('dom');
        }
        // Alt+M → 切換微观 (Micro)
        else if (e.key.toLowerCase() === 'm' && rightMode !== 'micro') {
          e.preventDefault();
          setRightMode('micro');
        }
        // Alt+C → 切換 K 線圖 (Chart mode)
        else if (e.key.toLowerCase() === 'c' && chartMode !== 'chart') {
          e.preventDefault();
          setChartMode('chart');
        }
        // Alt+O → 切換期權 (Options mode)
        else if (e.key.toLowerCase() === 'o' && chartMode !== 'options') {
          e.preventDefault();
          setChartMode('options');
        }
      }

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
        '3': '5m',   // 5 日
        '4': '1d',   // 日 K
        '5': '1w',   // 周 K
        '6': '1M',   // 月 K
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

  // 注：原 PROD-04a「盯盘模式全屏 K线 + 悬浮球自选」布局因 FloatingWatchlist 悬浮球被顶部导航栏
  // 遮挡导致自选列表无法打开、全屏容器内 K 线高度塌陷导致拉不到数据，已弃用。
  // 现 watch 场景回落到下方经充分验证的标准三栏布局（WatchlistSidebar + 主图 K线 + 盘口），
  // 同时保留 monitor / research 的专属布局。WatchScene 仅作为场景标识用于密度/AI 角色切换。

  return (
    <div className="flex flex-col h-[calc(100vh-80px)] min-h-[600px] w-full bg-background/50 rounded-xl">
      {/* 顶部标题区（对齐 Figma 设计稿：个股工作台 STOCK WORKBENCH + 多时区时钟 + 日期） */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40 bg-secondary/10 rounded-t-xl">
        <div className="h-1.5 w-1.5 rounded-full bg-primary" />
        {/* 标题随中列 [K 线 | 期权] 模式联动（Figma Frame 4 / Frame 5）+ 场景模式 */}
        <h1 className="text-base font-bold tracking-tight">
          {currentScene === 'research' ? '研究工作台' : currentScene === 'monitor' ? '监控工作台' : '个股工作台'}
        </h1>
        <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
          {chartMode === 'options' ? 'OPTION WORKBENCH' : 'STOCK WORKBENCH'}
        </span>
        {/* 场景徽章 */}
        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded border border-border/50 bg-secondary/50 text-muted-foreground">
          {SCENE_META[currentScene]?.emoji} {SCENE_META[currentScene]?.short}
        </span>
        {/* 模式副标题（设计稿中列模式说明，随模式联动） */}
        <span className="ml-3 text-[10px] text-muted-foreground/70 hidden md:inline">
          {chartMode === 'options'
            ? '申报模式 → 一中列 [K线/期权] 切换 顶部"期权波动率曲面"'
            : '最近盯入口:市场感知 → 行情与高频盘口（建议报名:个股工作台）'}
        </span>
        {/* 右上：当前期权标的徽章（仅期权模式，设计稿 Frame 5）+ 多时钟 + 日期 */}
        <div className="ml-auto flex items-center gap-3">
          {chartMode === 'options' && (
            <span className="hidden md:flex items-center gap-2 text-[10px] font-mono border border-amber-500/30 bg-amber-500/5 rounded px-2 py-0.5">
              <span className="text-foreground/80">{selectedSymbol}</span>
              <span className="text-foreground">1 秒价</span>
              <span className="text-amber-400/80">· 自动选中</span>
            </span>
          )}
          <MarketClocks />
          <span className="hidden sm:inline text-[10px] font-mono text-muted-foreground bg-secondary/50 border border-border/30 rounded px-2 py-0.5">
            {new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Hong_Kong' }).format(new Date())} HKT
          </span>
        </div>
      </div>

      {/* 主面板三栏区 */}
      <div className="resp-auto-panels resp-3col relative flex flex-1 min-h-0 w-full p-1">
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
          <div className="flex items-center justify-between px-3 py-1 border-b border-border/40 bg-secondary/10 shrink-0 gap-2">
            <div className="inline-flex rounded-md border border-border/50 p-0.5">
              {(['chart', 'options'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setChartMode(m)}
                  className={cn(
                    "text-[10px] px-2.5 py-0.5 rounded transition-colors",
                    chartMode === m ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {m === 'chart' ? 'K线' : '期权'}
                </button>
              ))}
            </div>
            {chartMode === 'chart' && (
              <button
                onClick={() => setCompareMode(!compareMode)}
                className={cn("text-[10px] px-2 py-0.5 rounded border border-border/50 transition-colors", compareMode ? "bg-primary/20 text-primary" : "bg-background hover:bg-secondary text-muted-foreground")}
              >
                {compareMode ? '退出同步对比' : '同步对比'}
              </button>
            )}
          </div>
          {/* AI-01: 默认/研究三栏场景也挂载异动解说联动——与 compare/watch 场景一致 */}
          <AnomalyFlash symbol={selectedSymbol} className="h-full">
            {chartMode === 'options' ? (
              <OptionModePanel symbol={selectedSymbol} />
            ) : hasData ? (
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

        {/* ── Right: DOM / 微观 ────────────────────────────── */}
        <Panel defaultSize={20} minSize={15} className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between px-3 py-1 border-b border-border/40 bg-secondary/10 shrink-0 rounded-lg">
            <div className="inline-flex rounded-md border border-border/50 p-0.5">
              {(['dom', 'micro', 'persist'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setRightMode(m)}
                  className={cn(
                    "text-[10px] px-2.5 py-0.5 rounded transition-colors",
                    rightMode === m ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {m === 'dom' ? '盘口' : m === 'micro' ? '微观' : '选择持久化'}
                </button>
              ))}
            </div>
          </div>
          <PanelErrorBoundary name="OrderBookPanel">
          {rightMode === 'micro' ? (
            <MicroPanel symbol={selectedSymbol} />
          ) : rightMode === 'persist' ? (
            <div className="glass-card rounded-xl overflow-hidden flex flex-col flex-1 shadow-sm border-border/40 p-4 gap-3 overflow-y-auto">
              <div className="text-[10px] font-semibold text-muted-foreground uppercase">标的视图偏好</div>
              {/* 当前标的已保存偏好快照 */}
              <div className="rounded-lg border border-border/40 bg-secondary/10 p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-mono text-foreground/90">{selectedSymbol}</span>
                  <span className="text-[9px] text-muted-foreground/70">{savedPrefs[selectedSymbol] ? '已保存' : '未保存'}</span>
                </div>
                {savedPrefs[selectedSymbol] ? (
                  <div className="text-[10px] text-muted-foreground/80 leading-5">
                    周期 <span className="text-foreground/90">{PERIOD_LABEL[savedPrefs[selectedSymbol].period] ?? savedPrefs[selectedSymbol].period}</span>
                    {' · '}模式 <span className="text-foreground/90">{savedPrefs[selectedSymbol].chartMode === 'options' ? '期权' : 'K线'}</span>
                    {' · '}右栏 <span className="text-foreground/90">{savedPrefs[selectedSymbol].rightMode === 'micro' ? '微观' : '盘口'}</span>
                  </div>
                ) : (
                  <div className="text-[10px] text-muted-foreground/70 leading-5">当前视图尚未保存，切换周期/模式后将自动记录。</div>
                )}
              </div>
              {/* 操作按钮 */}
              <div className="flex gap-2">
                <button
                  onClick={() => setSavedPrefs((prev) => { const next = { ...prev, [selectedSymbol]: { period: selectedPeriod, chartMode, rightMode: rightMode === 'persist' ? 'micro' : rightMode } as SymbolViewPref }; writeViewPrefs(next); return next })}
                  className="flex-1 text-[10px] px-2 py-1.5 rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                >
                  保存当前视图
                </button>
                {savedPrefs[selectedSymbol] && (
                  <button
                    onClick={() => setSavedPrefs((prev) => { const next = { ...prev }; delete next[selectedSymbol]; writeViewPrefs(next); return next })}
                    className="text-[10px] px-2 py-1.5 rounded border border-border/50 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    清除
                  </button>
                )}
              </div>
              {/* 已保存标的列表：点击应用偏好并切换标的 */}
              <div className="mt-1">
                <div className="text-[9px] font-semibold text-muted-foreground/70 uppercase mb-1.5">已保存标的（点击恢复）</div>
                {Object.keys(savedPrefs).length === 0 ? (
                  <div className="text-[10px] text-muted-foreground/60">暂无其它已保存标的。</div>
                ) : (
                  <div className="flex flex-col gap-1">
                    {Object.entries(savedPrefs).map(([sym, p]) => (
                      <button
                        key={sym}
                        onClick={() => { setSelectedSymbol(sym); setSelectedPeriod(p.period); setChartMode(p.chartMode); setRightMode(p.rightMode) }}
                        className={cn(
                          "flex items-center justify-between text-[10px] px-2 py-1.5 rounded border transition-colors",
                          sym === selectedSymbol ? "border-primary/40 bg-primary/10 text-primary" : "border-border/40 text-muted-foreground hover:text-foreground hover:border-border/70",
                        )}
                      >
                        <span className="font-mono">{sym}</span>
                        <span className="text-muted-foreground/70">{PERIOD_LABEL[p.period] ?? p.period}{p.chartMode === 'options' ? '·期权' : ''}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              <OrderBookDepthPanel symbol={selectedSymbol} />
              <BrokerPanel symbol={selectedSymbol} />
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

      {/* PROD-05 深化：超宽屏 21:9 三栏之一（行情+策略/新闻+AI），≥2560px 由 .resp-3col 揭示 */}
      <div data-ultrawide-ai className="hidden w-[360px] flex-shrink-0 min-h-0 border-l border-border/40">
        <AIChat />
      </div>
      </div>

      {/* 底部 footer（对齐 Figma 设计稿：键盘快捷键 + 数据源版权） */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t border-border/40 bg-secondary/10 text-[10px] text-muted-foreground/80 rounded-b-xl">
        <span className="flex items-center gap-2 flex-wrap">
          <span>键盘 <kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">↑</kbd>/<kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">↓</kbd> 切换周期</span>
          <span>·</span>
          <span><kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">Alt+D</kbd>/<kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">Alt+M</kbd> 盘口/微观</span>
          <span>·</span>
          <span><kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">Alt+C</kbd>/<kbd className="px-1 py-0.5 rounded bg-secondary/60 border border-border/40 font-mono text-[9px]">Alt+O</kbd> K 线/期权</span>
          <span>·</span>
          <span>休市时段醒收 K 线</span>
          <span>·</span>
          <span>续归技术形态标签</span>
        </span>
        <span className="flex items-center gap-1.5 font-mono">
          数据源·Futu OpenD · Lightweight-Charts
        </span>
      </div>
    </div>
  )
}
