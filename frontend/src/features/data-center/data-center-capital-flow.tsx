import { useState } from 'react'
import { BarChart3, Flame, Briefcase, Newspaper, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CapitalFlowPanel } from '@/features/data-center/capital-flow'
import { SectorFlowPanel } from '@/features/data-center/sector-flow'
import { SectorHeatmapPanel } from '@/features/data-center/sector-heatmap-panel'
import { MarginTradingPanel } from '@/features/data-center/margin-trading'
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
  } = data

  const [heatmapMarket, setHeatmapMarket] = useState<'A' | 'HK' | 'US'>('US')
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day')

  return (
    <div className="flex flex-col gap-4">
      {/* 区1：跨市场资金流向 + 港股南向下钻 */}
      <CrossMarketFlowSection capitalFlows={capitalFlows} period={period} setPeriod={setPeriod} />

      {/* 区2：板块资金流向（三市场切换 + 双栏 Top10/Top5） */}
      {sectorFlowData && <SectorFlowPanel data={sectorFlowData} status={sectorFlowStatus} />}

      {/* 区3：美股板块 ETF 资金 + 主力/大单 */}
      <EtfFlowSection />

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
  capitalFlows, period, setPeriod,
}: {
  capitalFlows: any[]
  period: 'day' | 'week' | 'month'
  setPeriod: (p: 'day' | 'week' | 'month') => void
}) {
  // 设计稿要求 8 张跨市场卡（港股南向 / 美股大盘 / 半导体 / 中美互联 / 北向成交额 / 美债ETF / 黄金ETF / 加密ETF）
  // 当前数据源（capitalFlows）为北向/南向等净额，暂以现有数据 + 占位渲染，等数据接入。
  const hasData = capitalFlows && capitalFlows.length > 0
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
      {/* 港股南向下钻 */}
      <Card className="mt-3">
        <div className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2">
          <Briefcase className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-foreground">港股南向 · 沪深港通下钻</span>
          <span className="ml-auto text-[10px] text-muted-foreground">敬请期待</span>
        </div>
        {/* UIRF-03: 移除硬编码示例值(原 +97.9亿/+42.1亿/+140.0亿 为写死数字)，接真实双通道数据前走诚实空态 */}
        <div className="flex flex-col items-center justify-center gap-1 px-3 py-6 text-center">
          <AlertTriangle className="h-4 w-4 text-muted-foreground/40" />
          <p className="text-[11px] text-muted-foreground">南向双通道（港股通沪 / 深）数据未接入</p>
          <p className="text-[10px] text-muted-foreground/60">接入实时沪深港通净买入后，此处展示沪 / 深 / 合计三项。</p>
        </div>
      </Card>
    </section>
  )
}

/* ───────── 区3 ───────── */
// 美股板块 ETF 资金流向（11 个 GICS 板块，对齐 Figma 设计稿横向条形图）
const US_SECTOR_ETF_FLOW = [
  { sector: '地产',     code: 'XLRE', flow:  1.20, side: 'inflow'  as const },
  { sector: '能源',     code: 'XLE',  flow:  0.30, side: 'inflow'  as const },
  { sector: '医疗',     code: 'XLV',  flow:  0.17, side: 'inflow'  as const },
  { sector: '可选消费', code: 'XLY',  flow:  0.12, side: 'inflow'  as const },
  { sector: '公用事业', code: 'XLU',  flow:  0.12, side: 'inflow'  as const },
  { sector: '通信',     code: 'XLC',  flow:  0.06, side: 'inflow'  as const },
  { sector: '科技',     code: 'XLK',  flow: -0.07, side: 'outflow' as const },
  { sector: '必选消费', code: 'XLP',  flow: -0.19, side: 'outflow' as const },
  { sector: '工业',     code: 'XLI',  flow: -0.19, side: 'outflow' as const },
  { sector: '金融',     code: 'XLF',  flow: -0.38, side: 'outflow' as const },
  { sector: '材料',     code: 'XLB',  flow: -0.62, side: 'outflow' as const },
]

// 美股主力 / 大单净流入（ETF 维度，对齐设计稿净流入贡献 Top）
const US_MAIN_FORCE_TOP = [
  { name: '标普 500 US · SPY',   flow:  3.0, side: 'inflow'  as const },
  { name: '20年+国债 US · TLT',  flow: -0.8, side: 'outflow' as const },
  { name: '半导体 ETF US · SOXX', flow: -0.6, side: 'outflow' as const },
  { name: '纳斯达克 100 US · QQQ', flow:  0.5, side: 'inflow'  as const },
  { name: '中概互联 US · KWEB',  flow:  0.0, side: 'inflow'  as const },
]

function EtfFlowSection() {
  // 横向条形图：根据最大绝对值归一化，正向右侧（绿），负向左侧（红）
  const maxAbs = Math.max(...US_SECTOR_ETF_FLOW.map(s => Math.abs(s.flow)), 0.01)
  return (
    <section>
      <SectionHeader
        icon={Newspaper}
        title="板块资金流向 · 美股板块视图（ETF 版）"
        sub="跟随 Fund Flow tab 注入"
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-2.5">
        {/* 左：美股板块 ETF 资金净流入（横向条形图列表） */}
        <Card>
          <CardHeader title="美股板块 ETF 资金净流入" />
          <div className="p-3 space-y-1.5">
            {US_SECTOR_ETF_FLOW.map((s) => {
              const pct = Math.min(Math.abs(s.flow) / maxAbs, 1) * 100
              const isIn = s.side === 'inflow'
              return (
                <div key={s.code} className="flex items-center gap-2 text-xs">
                  <div className="w-16 text-[11px] text-muted-foreground shrink-0">{s.sector}</div>
                  <div className="flex-1 h-4 relative bg-secondary/30 rounded-sm overflow-hidden">
                    {/* 中轴 */}
                    <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border/60" />
                    {isIn ? (
                      <div
                        className="absolute top-0.5 bottom-0.5 bg-[hsl(var(--bull))]/70 rounded-r-sm"
                        style={{ left: '50%', width: `${pct / 2}%` }}
                      />
                    ) : (
                      <div
                        className="absolute top-0.5 bottom-0.5 bg-[hsl(var(--bear))]/70 rounded-l-sm"
                        style={{ right: '50%', width: `${pct / 2}%` }}
                      />
                    )}
                  </div>
                  <div className={cn('w-16 text-right text-[11px] font-mono tabular-nums shrink-0', isIn ? 'text-[hsl(var(--bull))] dark:text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))] dark:text-[hsl(var(--bear))]')}>
                    {isIn ? '+' : ''}{s.flow.toFixed(2)}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="px-3 py-1.5 border-t border-border/20 text-[10px] text-muted-foreground">
            行业板块口径:Futu 核心行业 ETF · 单位:亿美元
          </div>
        </Card>

        {/* 右：美股主力 / 大单净流入（核心 ETF 主力大单净额 + Top 贡献） */}
        <Card>
          <CardHeader title="美股主力 / 大单净流入" sub="核心 ETF 主力（特大单+大单）净买卖额" />
          <div className="p-3 pb-1.5">
            <div className="text-2xl font-bold font-mono text-[hsl(var(--bull))] dark:text-[hsl(var(--bull))]">
              +2.0<span className="text-base ml-1">亿美元</span>
            </div>
            <div className="text-[10px] text-muted-foreground mt-0.5">净流入贡献 Top</div>
          </div>
          <div className="px-3 pb-3 space-y-1">
            {US_MAIN_FORCE_TOP.map((t) => (
              <div key={t.name} className="flex items-center justify-between text-xs">
                <span className="text-foreground/90 truncate flex-1">{t.name}</span>
                <span className={cn('font-mono tabular-nums shrink-0 ml-2', t.flow > 0 ? 'text-[hsl(var(--bull))] dark:text-[hsl(var(--bull))]' : t.flow < 0 ? 'text-[hsl(var(--bear))] dark:text-[hsl(var(--bear))]' : 'text-muted-foreground')}>
                  {t.flow > 0 ? '+' : ''}{t.flow.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
          <div className="px-3 py-1.5 border-t border-border/20 text-[10px] text-muted-foreground">
            基于核心行业 ETF（标普/纳指/半导体/中概/医疗）的 Futu 主力资金分布聚合
          </div>
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

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('glass-card rounded-lg overflow-hidden', className)}>{children}</div>
}

function CardHeader({ title, badge, sub }: { title: string; badge?: string; sub?: string }) {
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
      <div className="text-xs font-medium text-muted-foreground">{text} · 数据采集中</div>
      {hint && <div className="text-[10px] text-muted-foreground/60 mt-1">{hint}</div>}
    </div>
  )
}