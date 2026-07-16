'use client'

import React from 'react'
import { ShieldAlert, GitPullRequest } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { AlgoOrderModal, OrderDetailModal } from './oms-modals'
import { useOms } from './use-oms'
import { OmsBotGrid } from './oms-bot-grid'
import { OmsConsole } from './oms-console'
import { MODE_META, formatModeLabel } from './trading-mode-types'

export function OMSModule() {
  const {
    bots,
    activeOrders,
    historicalTrades,
    algoExecutions,
    positions,
    cancelingOrders,
    futuStatus,
    showAlgoModal,
    setShowAlgoModal,
    selectedOrder,
    setSelectedOrder,
    isConsoleOpen,
    setIsConsoleOpen,
    isKilled,
    isStale,
    tradingMode,
    logsEndRefs,
    handleKillSwitch,
    handleModeSwitch,
    handleCancelOrder,
    handleToggleBotStatus,
    handleStopBot,
  } = useOms()

  return (
    <div className="relative h-[calc(100vh-80px)] w-full flex flex-col overflow-hidden">
      
      {showAlgoModal && <AlgoOrderModal onClose={() => setShowAlgoModal(false)} />}
      {selectedOrder && <OrderDetailModal order={selectedOrder} onClose={() => setSelectedOrder(null)} />}
      
      {/* 💡 断流优雅降级保护 */}
      {isStale && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 z-[100]">
          <ShieldAlert className="h-12 w-12 text-amber-500 animate-pulse drop-shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
          <p className="mt-4 text-lg font-bold text-amber-500">OMS 数据网关断开 (STALE)</p>
          <p className="text-sm text-muted-foreground mt-1">正在尝试重新连接订单总线，页面状态已挂起...</p>
        </div>
      )}

      {/* 模式切换入口（全局横幅在 Layout；此处保留 OMS 快捷切换） */}
      <div className="flex-shrink-0 mb-2 flex items-center justify-between text-xs text-muted-foreground">
        <span className={cn('font-bold font-mono', MODE_META[tradingMode].chipClass)}>
          OMS · {formatModeLabel(tradingMode)}
        </span>
        <button
          type="button"
          onClick={handleModeSwitch}
          className="px-2 py-0.5 rounded border border-border/50 hover:bg-muted/50 transition-colors text-[10px] font-bold"
        >
          切换模式
        </button>
      </div>

      {/* ── Top Bar & Kill Switch ─────────────────────────────────────────── */}
      <div className="flex-shrink-0 mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-1.5 rounded-full bg-amber-500 dark:bg-amber-400" aria-hidden="true" />
          <h1 className="text-base font-bold tracking-tight">订单中枢与算力节点</h1>
          <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
            OMS & Live Bots
          </span>
        </div>
        
        <div className="flex items-center gap-3">
          <Button 
            onClick={() => setShowAlgoModal(true)}
            variant="outline"
            className="h-9 px-4 font-bold border-indigo-500/30 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/10 shadow-sm"
          >
            <GitPullRequest className="w-4 h-4 mr-1.5" />
            新建算法单
          </Button>

          <Button 
            onClick={handleKillSwitch}
            disabled={isKilled}
            className={cn(
              "h-9 px-6 font-bold tracking-widest uppercase transition-all duration-300 shadow-lg border",
              isKilled 
                ? "bg-red-950 text-red-500/50 border-red-900 cursor-not-allowed" 
                : "bg-red-600 hover:bg-red-500 text-white border-red-500 shadow-[0_0_15px_rgba(220,38,38,0.4)] hover:shadow-[0_0_25px_rgba(220,38,38,0.6)] animate-pulse"
            )}
          >
            <ShieldAlert className="w-4 h-4 mr-2" />
            {isKilled ? "已熔断 (KILLED)" : "全局熔断 (KILL SWITCH)"}
          </Button>
        </div>
      </div>

      <OmsBotGrid
        bots={bots}
        isKilled={isKilled}
        logsEndRefs={logsEndRefs}
        onToggleBotStatus={handleToggleBotStatus}
        onStopBot={handleStopBot}
      />

      <OmsConsole
        isConsoleOpen={isConsoleOpen}
        setIsConsoleOpen={setIsConsoleOpen}
        activeOrders={activeOrders}
        historicalTrades={historicalTrades}
        algoExecutions={algoExecutions}
        positions={positions}
        cancelingOrders={cancelingOrders}
        futuStatus={futuStatus}
        onSelectOrder={setSelectedOrder}
        onCancelOrder={handleCancelOrder}
      />
    </div>
  )
}
