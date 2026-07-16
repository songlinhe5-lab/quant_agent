'use client'

import React from 'react'
import { Terminal, ListOrdered, History, GitPullRequest, Activity, ChevronUp, ChevronDown, MapPin } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import type { ActiveOrder, HistoricalTrade, AlgoExecution, Position } from './oms-types'

interface OmsConsoleProps {
  isConsoleOpen: boolean
  setIsConsoleOpen: (open: boolean) => void
  activeOrders: ActiveOrder[]
  historicalTrades: HistoricalTrade[]
  algoExecutions: AlgoExecution[]
  positions: Position[]
  cancelingOrders: Set<string>
  futuStatus: { connected: boolean; status: string; error_msg?: string } | null
  onSelectOrder: (order: ActiveOrder) => void
  onCancelOrder: (orderId: string) => void
}

export function OmsConsole({
  isConsoleOpen,
  setIsConsoleOpen,
  activeOrders,
  historicalTrades,
  algoExecutions,
  positions,
  cancelingOrders,
  futuStatus,
  onSelectOrder,
  onCancelOrder,
}: OmsConsoleProps) {
  return (
    <div className={cn(
      "absolute bottom-0 left-0 right-0 glass-card border-t border-border/50 shadow-2xl transition-all duration-300 flex flex-col z-50",
      isConsoleOpen ? "h-[350px] translate-y-0" : "h-[40px] translate-y-[calc(100%-40px)]"
    )}>
      <div 
        className="h-[40px] px-4 flex items-center justify-between cursor-pointer bg-secondary/30 hover:bg-secondary/50 transition-colors shrink-0"
        onClick={() => setIsConsoleOpen(!isConsoleOpen)}
      >
        <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-wider">
          <Terminal className="w-4 h-4" />
          OMS 控制台 (Console)
        </div>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-mono">
          <span className="hidden sm:inline-flex items-center gap-1"><Activity className="w-3 h-3 text-emerald-500" /> API: 12ms</span>
          <span className="hidden sm:inline-block">快捷键: ~</span>
          {isConsoleOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
        </div>
      </div>

      {isConsoleOpen && (
        <div className="flex-1 overflow-hidden bg-background">
          <Tabs defaultValue="active" className="h-full flex flex-col">
            <TabsList className="bg-transparent border-b border-border/30 rounded-none h-10 px-4 justify-start shrink-0">
              <TabsTrigger value="active" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                <ListOrdered className="w-3.5 h-3.5 mr-1.5" /> 活动挂单 ({activeOrders.length})
              </TabsTrigger>
              <TabsTrigger value="history" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                <History className="w-3.5 h-3.5 mr-1.5" /> 历史成交
              </TabsTrigger>
              <TabsTrigger value="algo" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                <GitPullRequest className="w-3.5 h-3.5 mr-1.5" /> 算法拆单进度
              </TabsTrigger>
              <TabsTrigger value="positions" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                <MapPin className="w-3.5 h-3.5 mr-1.5" /> 真实持仓 ({positions.length})
              </TabsTrigger>
            </TabsList>

            {/* Active Orders Grid */}
            <TabsContent value="active" className="flex-1 m-0 overflow-auto custom-scrollbar">
              <table className="w-full text-xs text-left whitespace-nowrap">
                <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">订单号</th>
                    <th className="px-4 py-2.5 font-medium">时间</th>
                    <th className="px-4 py-2.5 font-medium">标的</th>
                    <th className="px-4 py-2.5 font-medium">方向</th>
                    <th className="px-4 py-2.5 font-medium text-right">报单价</th>
                    <th className="px-4 py-2.5 font-medium text-right">数量</th>
                    <th className="px-4 py-2.5 font-medium text-right">已成交</th>
                    <th className="px-4 py-2.5 font-medium text-center">状态</th>
                    <th className="px-4 py-2.5 font-medium text-center">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20 font-mono">
                  {activeOrders.map(order => (
                    <tr key={order.id} className="hover:bg-secondary/10 transition-colors cursor-pointer" onClick={() => onSelectOrder(order)}>
                      <td className="px-4 py-2 text-muted-foreground">{order.id}</td>
                      <td className="px-4 py-2 text-muted-foreground">{order.time}</td>
                      <td className="px-4 py-2 font-bold text-foreground">{order.symbol}</td>
                      <td className="px-4 py-2">
                        <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]", order.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
                          {order.side}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">{order.price}</td>
                      <td className="px-4 py-2 text-right">{order.qty}</td>
                      <td className="px-4 py-2 text-right">{order.filled}</td>
                      <td className="px-4 py-2 text-center">
                        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border", 
                          order.status === 'PENDING' ? 'border-amber-500/30 text-amber-500' : 
                          order.status === 'PARTIALLY_FILLED' ? 'border-sky-500/30 text-sky-500' : 
                          'border-slate-500/30 text-slate-500'
                        )}>
                          {order.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <button 
                          onClick={(e) => { e.stopPropagation(); onCancelOrder(order.id); }}
                          disabled={cancelingOrders.has(order.id)}
                          className="text-[10px] text-red-500 hover:text-red-400 hover:underline disabled:opacity-50 disabled:no-underline disabled:cursor-not-allowed"
                        >
                          {cancelingOrders.has(order.id) ? '撤单中...' : '撤单'}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {activeOrders.length === 0 && (
                    <tr><td colSpan={9} className="text-center py-8 text-muted-foreground">暂无活动挂单</td></tr>
                  )}
                </tbody>
              </table>
            </TabsContent>

            {/* Historical Trades Grid */}
            <TabsContent value="history" className="flex-1 m-0 overflow-auto custom-scrollbar">
              <table className="w-full text-xs text-left whitespace-nowrap">
                <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">成交编号</th>
                    <th className="px-4 py-2.5 font-medium">时间</th>
                    <th className="px-4 py-2.5 font-medium">标的</th>
                    <th className="px-4 py-2.5 font-medium">方向</th>
                    <th className="px-4 py-2.5 font-medium text-right">成交均价</th>
                    <th className="px-4 py-2.5 font-medium text-right">数量</th>
                    <th className="px-4 py-2.5 font-medium text-right">实现盈亏</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20 font-mono">
                  {historicalTrades.map(trade => (
                    <tr key={trade.id} className="hover:bg-secondary/10 transition-colors">
                      <td className="px-4 py-2 text-muted-foreground">{trade.id}</td>
                      <td className="px-4 py-2 text-muted-foreground">{trade.time}</td>
                      <td className="px-4 py-2 font-bold text-foreground">{trade.symbol}</td>
                      <td className="px-4 py-2">
                        <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]", trade.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
                          {trade.side}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">{trade.avg_price}</td>
                      <td className="px-4 py-2 text-right">{trade.qty}</td>
                      <td className={cn("px-4 py-2 text-right font-bold", trade.pnl > 0 ? "text-emerald-500" : trade.pnl < 0 ? "text-red-500" : "text-muted-foreground")}>
                        {trade.pnl > 0 ? '+' : ''}{trade.pnl !== 0 ? trade.pnl.toFixed(2) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabsContent>

            {/* Algo Execution Grid */}
            <TabsContent value="algo" className="flex-1 m-0 overflow-auto custom-scrollbar p-4 flex flex-col gap-4">
              {algoExecutions.map(algo => (
                <div key={algo.id} className="border border-border/40 rounded-lg p-4 bg-secondary/10 flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-foreground">{algo.algo_type} 拆单执行</span>
                      <span className="text-[10px] text-muted-foreground font-mono bg-secondary/50 px-2 py-0.5 rounded">{algo.symbol}</span>
                    </div>
                    <span className={cn("text-xs font-mono", algo.status === 'RUNNING' ? 'text-emerald-500' : algo.status === 'PAUSED' ? 'text-amber-500' : 'text-slate-500')}>
                      {algo.progress}% 完成 {algo.status === 'PAUSED' && '(暂停中)'}
                    </span>
                  </div>
                  <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
                    <div className={cn("h-full transition-all", algo.status === 'RUNNING' ? 'bg-emerald-500' : algo.status === 'PAUSED' ? 'bg-amber-500' : 'bg-slate-500')} style={{ width: `${algo.progress}%` }} />
                  </div>
                  <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
                    <span>目标: {algo.target_qty} 股</span>
                    <span>已成: {algo.filled_qty} 股 | 均价: {algo.avg_price}</span>
                    <span>{algo.message || (algo.status === 'RUNNING' ? '算法正在执行中...' : '已结束')}</span>
                  </div>
                </div>
              ))}
              {algoExecutions.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground py-8">
                  <GitPullRequest className="h-8 w-8 mb-2 opacity-20" />
                  <p className="text-sm">暂无运行中的算法拆单任务</p>
                </div>
              )}
            </TabsContent>

            {/* Real Positions (OMS-04) */}
            <TabsContent value="positions" className="flex-1 m-0 overflow-auto custom-scrollbar">
              <table className="w-full text-xs text-left whitespace-nowrap">
                <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">代码</th>
                    <th className="px-4 py-2.5 font-medium">名称</th>
                    <th className="px-4 py-2.5 font-medium">方向</th>
                    <th className="px-4 py-2.5 font-medium text-right">数量</th>
                    <th className="px-4 py-2.5 font-medium text-right">成本价</th>
                    <th className="px-4 py-2.5 font-medium text-right">市值</th>
                    <th className="px-4 py-2.5 font-medium text-right">盈亏</th>
                    <th className="px-4 py-2.5 font-medium text-right">盈亏比</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20 font-mono">
                  {positions.map((pos, idx) => (
                    <tr key={`${pos.code}-${idx}`} className="hover:bg-secondary/10 transition-colors">
                      <td className="px-4 py-2 font-bold text-foreground">{pos.code}</td>
                      <td className="px-4 py-2 text-muted-foreground">{pos.stock_name || '-'}</td>
                      <td className="px-4 py-2">
                        <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]",
                          pos.position_side === 'LONG' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500'
                        )}>
                          {pos.position_side}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">{pos.qty}</td>
                      <td className="px-4 py-2 text-right">{pos.cost_price?.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right">{pos.market_val?.toFixed(0)}</td>
                      <td className={cn("px-4 py-2 text-right font-bold", pos.pl_val > 0 ? "text-emerald-500" : pos.pl_val < 0 ? "text-red-500" : "text-muted-foreground")}>
                        {pos.pl_val > 0 ? '+' : ''}{pos.pl_val?.toFixed(2) || '0.00'}
                      </td>
                      <td className={cn("px-4 py-2 text-right font-bold",
                        pos.pl_ratio > 0 ? "text-emerald-500" : pos.pl_ratio < 0 ? "text-red-500" : "text-muted-foreground"
                      )}>
                        {pos.pl_ratio > 0 ? '+' : ''}{pos.pl_ratio != null ? (pos.pl_ratio * 100).toFixed(2) + '%' : '-'}
                      </td>
                    </tr>
                  ))}
                  {positions.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center py-8">
                        {futuStatus === null ? (
                          <span className="text-muted-foreground">正在同步 Futu 持仓...</span>
                        ) : futuStatus.connected ? (
                          <span className="text-muted-foreground">当前无持仓</span>
                        ) : (
                          <div className="flex flex-col items-center gap-1">
                            <span className="text-red-400 font-medium">🔴 Futu OpenD 未连接（持仓不可用）</span>
                            {futuStatus.error_msg && (
                              <span className="text-[11px] text-muted-foreground font-mono">{futuStatus.error_msg}</span>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  )
}
