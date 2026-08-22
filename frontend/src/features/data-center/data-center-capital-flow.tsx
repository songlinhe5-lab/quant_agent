import { useState } from 'react'
import { BarChart3, Flame, Briefcase, Newspaper, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CapitalFlowPanel } from '@/features/data-center/capital-flow'
import { SectorFlowPanel } from '@/features/data-center/sector-flow'
import { SectorHeatmapPanel } from '@/features/data-center/sector-heatmap-panel'
import { MarginTradingPanel } from '@/features/data-center/margin-trading'
import { DragonTigerBoard } from '@/features/data-center/dragon-tiger-board'
import { BrokerQueuePanel } from '@/features/data-center/broker-queue-panel'
import type { useDashboardData as useDashboardDataType, HubTab } from '@/features/data-center/use-dashboard-data'

interface Props {
  data: ReturnType<typeof useDashboardDataType>
  onNavigate: (tab: HubTab, symbol?: string) => void
}

/**
 * 资金流 tab · Figma Frame 2（资金流向）整体布局。
 * 移除写死的单标的微观面板，兑现"宏观不出个股"。
 * 缺失数据源（跨市场 ETF 资金 / 美股板块 ETF / 美股主力大单 / 美股卖空）占位提示。
 */
export function CapitalFlowTab({ data, onNavigate }: Props) {
  void onNavigate
  const {
    capitalFlows, sectorFlowData, sectorFlowStatus,
    marginData, marginStatus, last,
    capitalFlowDashboard, aShareLhb, aShareLhbStatus,
    hkBrokerQueue, hkBrokerQueueStatus,
  } = data

  const [heatmapMarket, setHeatmapMarket] = useState<'A' | 'HK' | 'US'>('US')
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day')

  return (
    <div className="flex flex-col gap-4">
      {/* 区1：跨市场资金流向 + 港股南向下钻 */}
      <CrossMarketFlowSection
        capitalFlows={capitalFlows}
        period={period}
        setPeriod={setPeriod}
        hkConnect={capitalFlowDashboard?.hk_connect}
      />

      {/* 区2：板块资金流向（三市场切换 + 双栏 Top10/Top5） */}
      {sectorFlowData && <SectorFlowPanel data={sectorFlowData} status={sectorFlowStatus} />}

      {/* 区3：美股板块 ETF 资金 + 主力/大单 */}
      <EtfFlowSection
        usSectors={capitalFlowDashboard?.us}
        usBigOrder={capitalFlowDashboard?.us_big_order}
      />

      {/* 区4：FUNDFLOW-02 龙虎榜 / 经纪商席位 */}
      <DragonTigerBoard data={aShareLhb} status={aShareLhbStatus} />
      <BrokerQueuePanel data={hkBrokerQueue} status={hkBrokerQueueStatus} symbol="HK.00700" />

      {/* 区4：板块热力图（三市场切换） */}
      <section>
        <SectionHeader icon={Flame} title="板块热力图" sub="涨 32 · 平 5 · 跌 18（实时）" />
        <div className="flex items-center gap-2 mt-2.5 mb-1">
          <div className="inline-flex rounded-lg border border-border/60 p-0.5">
            {(['A', 'HK', 'US'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setHeatmapMarket(m)}
                className={cn(
                  'px-3 py-1 text-xs font-medium rounded-md transition-colors',
                  heatmapMarket === m
                    ? 'bg-primary text-primary-foreground'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                {m === 'A' ? 'A股' : m === 'HK' ? '港股' : '美股'}
              </button>
            ))}
          </div>
        </div>
        <SectorHeatmapPanel market={heatmapMarket} />
      </section>

      {/* 区5：卖空与两融区（MarginTradingPanel 内部 md:grid-cols-3 渲染 A股两融 / 港股 / 美股三市场卡，标题"卖空区指标"） */}
      <section>
        <MarginTradingPanel data={marginData} status={marginStatus} lastUpdated={last} />
      </section>
    </div>
  )
}

/* ───────── 区1 ───────── */
function CrossMarketFlowSection({
  capitalFlows, period, setPeriod, hkConnect,
}: {
  capitalFlows: any[]
  period: 'day' | 'week' | 'month'
  setPeriod: (p: 'day' | 'week' | 'month') => void
  hkConnect?: any
}) {
  // 设计稿要求 8 张跨市场卡（港股南向 / 美股大盘 / 半导体 / 中美互联 / 北向成交额 / 美债ETF / 黄金ETF / 加密ETF）
  // 当前数据源（capitalFlows）为北向/南向等净额，暂以现有数据 + 占位渲染，等数据接入。
  const hasData = capitalFlows && capitalFlows.length > 0
  const hasHkConnect = !!hkConnect && Array.isArray(hkConnect.channels) && hkConnect.channels.length > 0
  const fmtYi = (v: number) => {
    if (v == null || Number.isNaN(v)) return '—'
    const yi = v / 1e8
    return `${yi >= 0 ? '+' : ''}${yi.toFixed(1)}亿`
  }
  return (
    <section>
      <div className="flex items-center gap-2 mb-2.5">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-[15px] font-semibold text-foreground">跨市场资金流向</h2>
        <span className="text-[10px] text-muted-foreground/70">切换周期后卡片显示该期累计净流入 + 趋势线</span>
        <div className="ml-auto inline-flex rounded-lg border border-border/60 p-0.5">
          {(['day', 'week', 'month'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                'px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors',
                period === p ? 'bg-primary text-primary-foreground' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              {p === 'day' ? '日' : p === 'week' ? '周' : '月'}
            </button>
          ))}
        </div>
      </div>
      {hasData ? (
        <CapitalFlowPanel data={capitalFlows} />
      ) : (
        <Placeholder text="跨市场 ETF 资金流向" hint="港股南向 / 美股大盘 / 半导体 / 中美互联 / 北向成交额 / 美债ETF / 黄金ETF / 加密ETF" />
      )}

      {/* UIRF-07: 北向成交额中性卡 —— 港交所 2024-08 起停止披露北向资金净买入口径，仅余成交额 */}
      <Card className="mt-3">
        <CardHeader title="北向资金 · 成交额口径" sub="港交所 2024-08 起停止披露北向净买入" badge="中性" />
        <div className="flex flex-col items-center justify-center gap-1 px-3 py-5 text-center">
          <p className="text-[11px] text-muted-foreground">北向资金当前仅披露成交额，无净买入净额</p>
          <p className="text-[10px] text-muted-foreground/60">依据港交所 2024-08 数据披露规则调整，不再提供净买入额口径。</p>
        </div>
      </Card>

      {/* 港股南向下钻 */}
      <Card className="mt-3">
        <div className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2">
          <Briefcase className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-foreground">港股南向 · 沪深港通下钻</span>
          {hasHkConnect && (
            <span className="ml-auto text-[10px] text-muted-foreground">
              合计 {fmtYi(hkConnect.total_net_buy)} · {hkConnect.unit || ''}
            </span>
          )}
        </div>
        {hasHkConnect ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 px-3 py-3">
            {hkConnect.channels.map((ch: any, i: number) => (
              <div key={ch.name || i} className="flex flex-col rounded-md border border-border/40 px-3 py-2">
                <span className="text-[11px] text-muted-foreground">{ch.name}</span>
                <span className={cn('text-sm font-semibold', (ch.net_buy ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                  {fmtYi(ch.net_buy)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          /* 未接入真实数据时的诚实空态 */
          <div className="flex flex-col items-center justify-center gap-1 px-3 py-6 text-center">
            <AlertTriangle className="h-4 w-4 text-muted-foreground/40" />
            <p className="text-[11px] text-muted-foreground">南向双通道（港股通沪 / 深）数据未接入</p>
            <p className="text-[10px] text-muted-foreground/60">接入实时沪深港通净买入后，此处展示沪 / 深 / 合计三项。</p>
          </div>
        )}
      </Card>
    </section>
  )
}

/* ───────── 区3 ───────── */
function EtfFlowSection({ usSectors, usBigOrder }: { usSectors?: any; usBigOrder?: any }) {
  const hasSectors = !!usSectors && Array.isArray(usSectors.sectors) && usSectors.sectors.length > 0
  const hasBigOrder = !!usBigOrder && (usBigOrder.total_net_inflow != null || (Array.isArray(usBigOrder.breakdown) && usBigOrder.breakdown.length > 0))
  const fmtYi = (v: number) => {
    if (v == null || Number.isNaN(v)) return '—'
    const yi = v / 1e8
    return `${yi >= 0 ? '+' : ''}${yi.toFixed(1)}亿`
  }
  const maxAbs = hasSectors
    ? Math.max(...usSectors.sectors.map((s: any) => Math.abs(s.net_inflow || 0)), 1)
    : 1
  return (
    <section>
      <SectionHeader
        icon={Newspaper}
        title="板块资金流向 · 美股板块视图（ETF 版）"
        sub="跟随 Fund Flow tab 注入"
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-2.5">
        {/* 左：美股板块 ETF 资金净流入 */}
        <Card>
          <CardHeader title="美股板块 ETF 资金净流入" sub={usSectors?.unit} />
          {hasSectors ? (
            <div className="flex flex-col gap-1.5 px-3 py-3">
              {usSectors.sectors.map((s: any, i: number) => {
                const v = s.net_inflow || 0
                const pct = (Math.abs(v) / maxAbs) * 100
                return (
                  <div key={s.name || i} className="flex items-center gap-2">
                    <span className="w-20 truncate text-[11px] text-muted-foreground">{s.name}</span>
                    <div className="flex-1 h-2 rounded-full bg-border/30 overflow-hidden">
                      <div
                        className={cn('h-full', v >= 0 ? 'bg-emerald-400/70' : 'bg-rose-400/70')}
                        style={{ width: `${pct}%`, marginLeft: v >= 0 ? 0 : `calc(100% - ${pct}%)` }}
                      />
                    </div>
                    <span className={cn('w-16 text-right text-[11px] font-medium', v >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                      {fmtYi(v)}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-1 p-6 text-center">
              <AlertTriangle className="h-4 w-4 text-muted-foreground/40" />
              <p className="text-[11px] text-muted-foreground">美股板块 ETF 资金流数据未接入</p>
              <p className="text-[10px] text-muted-foreground/60">接入行业板块 ETF 净流入数据后，此处展示横向条形图。</p>
            </div>
          )}
        </Card>

        {/* 右：美股主力 / 大单净流入 */}
        <Card>
          <CardHeader title="美股主力 / 大单净流入" sub="核心 ETF 主力（特大单+大单）净买卖额" />
          {hasBigOrder ? (
            <div className="flex flex-col gap-2 px-3 py-3">
              <div className="flex items-baseline justify-between">
                <span className="text-[11px] text-muted-foreground">合计净流入</span>
                <span className={cn('text-sm font-semibold', (usBigOrder.total_net_inflow ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                  {fmtYi(usBigOrder.total_net_inflow)} {usBigOrder.unit || ''}
                </span>
              </div>
              {Array.isArray(usBigOrder.breakdown) && usBigOrder.breakdown.length > 0 && (
                <div className="flex flex-col gap-1 mt-1">
                  <span className="text-[10px] text-muted-foreground/70">Top 贡献</span>
                  {usBigOrder.breakdown.slice(0, 5).map((b: any, i: number) => (
                    <div key={b.ticker || i} className="flex items-center justify-between text-[11px]">
                      <span className="text-muted-foreground">{b.name || b.ticker}</span>
                      <span className={cn((b.net_inflow ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                        {fmtYi(b.net_inflow)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-1 p-6 text-center">
              <AlertTriangle className="h-4 w-4 text-muted-foreground/40" />
              <p className="text-[11px] text-muted-foreground">美股主力 / 大单数据未接入</p>
              <p className="text-[10px] text-muted-foreground/60">接入核心 ETF 主力资金分布后，此处展示净额与 Top 贡献。</p>
            </div>
          )}
        </Card>
      </div>
    </section>
  )
}

/* ───────── 公共组件 ───────── */
function SectionHeader({ icon: Icon, title, sub }: { icon: any; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
      {sub && <span className="text-[10px] text-muted-foreground/70">{sub}</span>}
    </div>
  )
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('glass-card rounded-lg overflow-hidden', className)}>{children}</div>
}

export function CardHeader({ title, badge, sub }: { title: string; badge?: string; sub?: string }) {
  return (
    <div className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2">
      <span className="text-xs font-semibold text-foreground">{title}</span>
      {sub && <span className="text-[10px] text-muted-foreground/70">{sub}</span>}
      {badge && <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded border border-border/40 text-muted-foreground">{badge}</span>}
    </div>
  )
}

function Placeholder({ text, hint, className }: { text: string; hint?: string; className?: string }) {
  return (
    <div className={cn('p-6 text-center', className)}>
      <div className="text-xs font-medium text-muted-foreground">{text} · 未接入</div>
      {hint && <div className="text-[10px] text-muted-foreground/60 mt-1">{hint}</div>}
    </div>
  )
}
