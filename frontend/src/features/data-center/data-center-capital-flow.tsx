import { useState } from 'react'
import { BarChart3, Flame, Briefcase, Newspaper } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CapitalFlowPanel } from '@/features/data-center/capital-flow'
import { SectorFlowPanel } from '@/features/data-center/sector-flow'
import { SectorHeatmapPanel } from '@/features/data-center/sector-heatmap-panel'
import { MarginTradingPanel } from '@/features/data-center/margin-trading'
import { ShortSellingPanel } from '@/features/data-center/short-selling-panel'
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
    shortSellingHasContent,
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

      {/* 区5：卖空与两融（三张等宽卡） */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Card>
          <CardHeader title="A股两融" badge="日更" />
          <MarginTradingPanel data={marginData} status={marginStatus} lastUpdated={last} />
        </Card>
        <Card>
          <CardHeader title="港股卖空" badge="日更" />
          <ShortSellingPanel ticker="HK.00700" mode="overview" />
        </Card>
        <Card>
          <CardHeader title="美股卖空" badge="半月报" />
          <Placeholder text="美股卖空 (CBOE)" hint="日均 3.69 亿股" />
        </Card>
      </div>
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
        <h2 className="text-sm font-semibold text-foreground">跨市场资金流向</h2>
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
          <span className="ml-2 text-[10px] text-muted-foreground">交易日 2026-08-18</span>
          <span className="ml-auto text-[10px] text-primary cursor-pointer">点击展开 →</span>
        </div>
        <div className="grid grid-cols-3 divide-x divide-border/30">
          <SubCell label="港股通(沪)" value="+97.9亿" sub="+213 / ↓386 · ▲0.07%" />
          <SubCell label="港股通(深)" value="+42.1亿" sub="+213 / ↓386 · ▲0.07%" />
          <SubCell label="南向合计净买入" value="+140.0亿" sub="跟随 日/周/月 周期切换" />
        </div>
      </Card>
    </section>
  )
}

function SubCell({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="px-3 py-3">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="text-xl font-bold font-mono text-emerald-400 mt-0.5">{value}</div>
      <div className="text-[10px] text-muted-foreground/80 font-mono mt-0.5">{sub}</div>
    </div>
  )
}

/* ───────── 区3 ───────── */
function EtfFlowSection() {
  return (
    <section>
      <SectionHeader icon={Newspaper} title="板块资金流向 · 美股板块视图（ETF版）" sub="跟随 Fund Flow tab 注入" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-2.5">
        <Card>
          <CardHeader title="美股板块 ETF 资金净流入" />
          <Placeholder text="板块 ETF 资金净流入条形图" hint="地产 / 能源 / 医疗 / 可选消费 / 公用事业 / 通信 / 科技 / 必选消费 / 工业 / 金融 / 材料" />
        </Card>
        <Card>
          <CardHeader title="美股主力 / 大单净流入" sub="核心 ETF 主力（大+特大单）净买卖额" />
          <div className="p-3">
            <div className="text-2xl font-bold font-mono text-emerald-400">+2.0 亿美元</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">净流入贡献 Top</div>
          </div>
          <Placeholder text="净流入贡献 Top 5" hint="标普500 SPY / 20年+国债 TLT / 半导体 SOXX / 纳斯达克100 QQQ / 中概互联 KWEB" className="border-t border-border/30" />
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
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
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