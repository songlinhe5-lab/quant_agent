/**
 * 回测结果展示：Tear Sheet KPIs + 图表 Tabs + 交易明细
 */

import { AlertTriangle, BarChart3, RotateCcw } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { BacktestEquityChart, BacktestUnderwaterChart, BacktestReturnsHistogram } from './backtest-charts'
import { ReproducibilityBadgeView } from '@/features/backtest/reproducibility-badge'
import { EmptyState, InitOverlay } from '@/components/ui/data-display'

interface BacktestResultsProps {
  backtestResult: any
  running: boolean
  progress: number
  progressStage: string
  isDebugMode: boolean
  currentTearSheet: { label: string; value: string; dir: number; note: string }[]
  reproBadge: any
  metrics: any
  curve: any[]
  underwaterDataComputed: any[]
  histogramData: any[]
  /** UIRF-02: 回测错误态 */
  error?: string | null
  onRetry?: () => void
  /** UIRF-01: 手动停止态（保留最后一次成功结果，明示未完成） */
  stopped?: boolean
}

export function BacktestResults({
  backtestResult, running, progress, progressStage, isDebugMode,
  currentTearSheet, reproBadge, metrics,
  curve, underwaterDataComputed, histogramData,
  error, onRetry, stopped,
}: BacktestResultsProps) {
  // §14.1/§14.2：区分「推演进行中」与「从未运行」两种空态。
  // running 且尚无结果 → 进度骨架屏（引擎已在撮合，不应提示"请运行"）；
  // 从未运行 → EmptyState 引导，禁止展示假净值曲线/假指标或静默空白。
  if (running && !backtestResult) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <InitOverlay
          variant="spinner"
          label={progressStage || '引擎正在撮合历史 K 线与订单…'}
          progress={progress}
        />
      </div>
    )
  }
  if (!backtestResult) {
    // UIRF-01: 已停止态——明示未完成且可重新运行，不静默回退到「请运行」引导
    if (stopped) {
      return (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            title="已手动停止"
            description="回测推演被中止，未产出结果。停止即断开流，后端任务异步取消；可重新运行。"
            action={onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="flex items-center gap-1.5 rounded-lg border border-border/50 bg-secondary/40 px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:bg-secondary/70 transition-colors"
              >
                <RotateCcw className="h-3 w-3" /> 重新运行
              </button>
            ) : undefined}
          />
        </div>
      )
    }
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState
          title="请运行回测推演"
          description="在左侧配置策略参数后点击「运行回测」，生成 Tear Sheet、权益曲线与成交明细。"
        />
      </div>
    )
  }
  // UIRF-02: 错误态 —— 后端报错/网络失败时显示错误卡 + 重试，进度停实际值，禁止「报错也显示完成」
  if (error) {
    return (
      <div className="rounded-xl border border-red-400/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 text-red-400">
          <AlertTriangle className="h-4 w-4" />
          <span className="text-xs font-bold">回测执行失败</span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-red-300/80">{error}</p>
        <p className="mt-1 text-[10px] text-red-400/60">进度停留在实际值（{progress}%），未伪造成「完成」。</p>
        <div className="mt-3 flex gap-2">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1.5 rounded-lg bg-red-500/15 border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-300 hover:bg-red-500/25 transition-colors"
            >
              <RotateCcw className="h-3 w-3" /> 重试
            </button>
          )}
        </div>
      </div>
    )
  }
  return (
    <>
      {/* UIRF-01: 已停止但保留最后一次成功结果——顶部提示条明示本次推演未完成 */
      stopped && (
        <div className="flex items-center justify-between gap-2 px-4 py-2.5 rounded-lg bg-secondary/40 border border-border/50">
          <p className="text-xs text-muted-foreground">
            <span className="font-bold text-foreground/90">已手动停止</span>
            · 下方为最后一次成功推演结果，本次中止未产生新数据。
          </p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1 rounded-md border border-border/50 px-2 py-1 text-[10px] font-semibold text-foreground/80 hover:bg-secondary/70 transition-colors"
            >
              <RotateCcw className="h-3 w-3" /> 重新运行
            </button>
          )}
        </div>
      )}

      {/* Disclaimer banner */}
      <div className="flex items-start gap-3 px-4 py-3 rounded-lg bg-amber-500/10 dark:bg-amber-400/8 border border-amber-500/20 dark:border-amber-400/20 transition-colors duration-300">
        <AlertTriangle className="h-4 w-4 text-amber-500 dark:text-amber-400 flex-shrink-0 mt-0.5 transition-colors duration-300" aria-hidden="true" />
        <p className="text-xs text-amber-700 dark:text-amber-300/80 leading-relaxed transition-colors duration-300">
          <span className="font-bold">免责声明：</span>回测结果仅供参考，不代表未来实盘收益。历史数据可能含有幸存者偏差，实际运行中的滑点、手续费、流动性约束均会导致结果偏差。严禁将回测夏普比率直接作为实盘风控依据。
        </p>
      </div>

      {/* Tear Sheet KPIs */}
      <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Tear Sheet · 核心指标</span>
          </div>
          <ReproducibilityBadgeView badge={reproBadge} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y divide-border/20">
          {currentTearSheet.map((m, i) => (
            <div key={i} className="px-4 py-3">
              <p className="text-[10px] text-muted-foreground mb-1">{m.label}</p>
              <p className={cn(
                'text-lg font-bold font-mono tabular-nums leading-tight transition-colors duration-300',
                m.dir > 0 ? 'text-emerald-600 dark:text-emerald-400' : m.dir < 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground'
              )}>{m.value}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">{m.note}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Charts Tabs */}
      <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
        <Tabs defaultValue="equity">
          <div className="border-b border-border/30 px-4">
            <TabsList className="bg-transparent p-0 gap-0 h-10">
              {[['equity','权益曲线'],['drawdown','水下时间'],['returns','收益分布'],['trades','交易明细'],['limit_orders','限价单'], ['debug_logs','调试日志']].map(([v, l]) => (
                <TabsTrigger key={v} value={v} className="text-xs px-3 h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                  {l}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value="equity" className="m-0 p-4">
            <div className="h-52">
              <BacktestEquityChart data={curve} />
            </div>
            <div className="flex gap-4 mt-2 text-[10px]">
              <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-emerald-500 dark:bg-emerald-400 rounded transition-colors duration-300" />策略净值</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground/40" />基准收益</span>
            </div>
          </TabsContent>

          <TabsContent value="drawdown" className="m-0 p-4">
            <div className="h-52">
              <BacktestUnderwaterChart data={underwaterDataComputed} maxDrawdown={metrics.max_drawdown} />
            </div>
          </TabsContent>

          <TabsContent value="returns" className="m-0 p-4">
            <div className="h-52">
              <BacktestReturnsHistogram data={histogramData} />
            </div>
          </TabsContent>

          <TabsContent value="trades" className="m-0">
            <TradesTable backtestResult={backtestResult} running={running} />
          </TabsContent>

          <TabsContent value="limit_orders" className="m-0">
            <LimitOrdersTable backtestResult={backtestResult} running={running} />
          </TabsContent>

          <TabsContent value="debug_logs" className="m-0">
            <div className="overflow-x-auto max-h-52 custom-scrollbar bg-black/90 p-3 rounded-b-lg">
              {backtestResult?.debug_logs && backtestResult.debug_logs.length > 0 ? (
                <div className="text-[10px] font-mono text-emerald-400/90 whitespace-pre-wrap leading-relaxed">
                  {backtestResult.debug_logs.join('\n')}
                </div>
              ) : (
                <div className="text-center text-muted-foreground text-xs py-8">
                  {isDebugMode ? '无有效交易引发的内部状态更新' : '未开启 Debug 模式。请在上方配置中勾选后重新执行。'}
                </div>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}

// ── 交易明细表 ──

function TradesTable({ backtestResult, running }: { backtestResult: any; running: boolean }) {
  return (
    <div className="overflow-x-auto max-h-52 custom-scrollbar">
      <table className="w-full text-xs" aria-label="交易明细">
        <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md">
          <tr className="border-b border-border/30 bg-secondary/20">
            <th className="px-4 py-2 text-left text-muted-foreground font-medium">日期</th>
            <th className="px-4 py-2 text-left text-muted-foreground font-medium">方向</th>
            <th className="px-4 py-2 text-right text-muted-foreground font-medium">成交价</th>
            <th className="px-4 py-2 text-right text-muted-foreground font-medium">股数</th>
            <th className="px-4 py-2 text-right text-muted-foreground font-medium">平仓盈亏</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/15">
          {backtestResult?.trades ? backtestResult.trades.map((trade: any, i: number) => (
            <tr key={i} className="hover:bg-secondary/25 transition-colors">
              <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{trade.date}</td>
              <td className="px-4 py-2.5 font-bold">
                <span className={cn("px-1.5 py-0.5 rounded text-[10px]", trade.action === 'BUY' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400')}>
                  {trade.action}
                </span>
              </td>
              <td className="px-4 py-2.5 text-right font-mono tabular-nums">${Number(trade.price).toFixed(2)}</td>
              <td className="px-4 py-2.5 text-right font-mono tabular-nums text-muted-foreground">{trade.shares}</td>
              <td className={cn('px-4 py-2.5 text-right font-mono font-bold tabular-nums transition-colors duration-300', trade.profit > 0 ? 'text-emerald-600 dark:text-emerald-400' : trade.profit < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                {trade.action === 'SELL' ? (trade.profit > 0 ? `+$${Number(trade.profit).toFixed(2)}` : `-$${Math.abs(Number(trade.profit)).toFixed(2)}`) : '-'}
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground text-xs">
                {running ? '回测执行中...' : '暂无交易记录'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ── 限价单表 ──

function LimitOrdersTable({ backtestResult, running }: { backtestResult: any; running: boolean }) {
  return (
    <div className="overflow-x-auto max-h-52 custom-scrollbar">
      <table className="w-full text-xs" aria-label="限价单明细">
        <thead className="sticky top-0 z-10 bg-slate-50/90 dark:bg-zinc-900/90 backdrop-blur-md">
          <tr className="border-b border-border/30 bg-secondary/20">
            <th className="px-4 py-2 text-left text-muted-foreground font-medium">挂单日</th>
            <th className="px-4 py-2 text-left text-muted-foreground font-medium">终结日</th>
            <th className="px-4 py-2 text-right text-muted-foreground font-medium">限价</th>
            <th className="px-4 py-2 text-center text-muted-foreground font-medium">状态</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/15">
          {backtestResult?.limit_orders && backtestResult.limit_orders.length > 0 ? backtestResult.limit_orders.map((order: any, i: number) => (
            <tr key={i} className="hover:bg-secondary/25 transition-colors">
              <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{order.start_date}</td>
              <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{order.end_date}</td>
              <td className="px-4 py-2.5 text-right font-mono tabular-nums text-amber-500 font-bold">${Number(order.price).toFixed(2)}</td>
              <td className="px-4 py-2.5 text-center">
                <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold border",
                  order.status === 'FILLED' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30' :
                  order.status === 'CANCELED' ? 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30' :
                  'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
                )}>
                  {order.status}
                </span>
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground text-xs">
                {running ? '回测执行中...' : '暂无追踪限价单记录'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
