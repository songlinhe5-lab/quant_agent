import { useMemo, useState } from 'react'
import { Globe2, Activity, CalendarClock, BarChart3, ArrowDownUp, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AssetButton } from './shared'
import { MarketSentimentPanel } from './market-sentiment'
import { MacroRiskRadar } from './macro-risk-radar'
import { OptionPcrPanel } from '@/features/options/option-pcr-panel'
import { useDashboardData, type HubTab } from './use-dashboard-data'

type DashData = ReturnType<typeof useDashboardData>

interface Props {
  data: DashData
  onNavigate: (tab: HubTab, symbol?: string) => void
}

// 前端按 symbol 映射资产类目，供 A 区类目筛选（后端 macroAssets 暂未下发 category）。
const ASSET_CATEGORY: Record<string, string> = {
  SPX: '指数', ES: '指数', IXIC: '指数', NQ: '指数', HSI: '指数',
  HSTECH: '指数', N225: '指数', XLK: '指数', XLE: '指数', KWEB: '指数', VIX: '指数',
  XAU: '商品', WTI: '商品', HG: '商品',
  'JPY=X': '外汇', 'DX-Y': '外汇', USDCNH: '外汇',
  TNX: '债券',
  BTC: '加密',
}

const CATEGORY_TABS = ['全部', '指数', '商品', '外汇', '债券', '加密'] as const

export function OverviewTab({ data, onNavigate }: Props) {
  const [cat, setCat] = useState<(typeof CATEGORY_TABS)[number]>('全部')

  const vixAsset = useMemo(() => data.assets.find((a: any) => a.symbol === 'VIX') ?? null, [data.assets])

  const filteredAssets = useMemo(() => {
    if (cat === '全部') return data.assets
    return data.assets.filter((a: any) => ASSET_CATEGORY[a.symbol] === cat)
  }, [data.assets, cat])

  // C 区·今日焦点 派生
  const todayHighEvents = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    return (data.events || [])
      .filter((ev: any) => (ev.importance === 'high' || ev.level === 'high') && String(ev.date || ev.time || '').slice(0, 10) === today)
      .slice(0, 4)
  }, [data.events])

  const upcomingEarnings = useMemo(() => {
    const now = Date.now()
    return (data.earnings || [])
      .filter((e: any) => e.reportDate && new Date(e.reportDate).getTime() >= now)
      .sort((a: any, b: any) => new Date(a.reportDate).getTime() - new Date(b.reportDate).getTime())
      .slice(0, 4)
  }, [data.earnings])

  const topInflows = useMemo(() => {
    return (data.capitalFlows || [])
      .filter((c: any) => (c.dir ?? 0) > 0)
      .sort((a: any, b: any) => (b.amount ?? 0) - (a.amount ?? 0))
      .slice(0, 4)
  }, [data.capitalFlows])

  return (
    <div className="space-y-5">
      {/* A 区 · 全球市场脉搏 */}
      <section>
        <div className="flex items-center gap-2 mb-2.5">
          <Globe2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold text-foreground">全球市场脉搏</h2>
          <span className="text-[10px] text-muted-foreground/70">跨市场大类资产实时快照</span>
          <div className="ml-auto flex items-center gap-1">
            {CATEGORY_TABS.map((c) => (
              <button
                key={c}
                onClick={() => setCat(c)}
                className={cn(
                  'px-2.5 py-1 text-[11px] rounded-full border transition-colors',
                  cat === c
                    ? 'bg-primary/15 text-primary border-primary/40'
                    : 'text-muted-foreground border-border/40 hover:bg-secondary/40',
                )}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
        {filteredAssets.length ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2.5">
            {filteredAssets.map((a: any) => (
              <AssetButton key={a.symbol} asset={a} />
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-muted-foreground border border-dashed border-border/40 rounded-lg">
            当前类目暂无资产数据
          </div>
        )}
      </section>

      {/* B 区 · 三卡 */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-1">
          <MarketSentimentPanel vixData={vixAsset} sentimentInd={data.sentimentInd} />
        </div>
        <div className="lg:col-span-1">
          <MacroRiskRadar
            radar={data.radar}
            radarInfo={data.radarInfo}
            setRadarInfo={data.setRadarInfo}
          />
        </div>
        <div className="lg:col-span-1 glass-card rounded-lg overflow-hidden flex flex-col">
          <div className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2">
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">PCR 期权情绪</span>
          </div>
          <div className="p-3 flex-1 overflow-y-auto max-h-64">
            <OptionPcrPanel />
          </div>
        </div>
      </section>

      {/* C 区 · 今日焦点 */}
      <section>
        <div className="flex items-center gap-2 mb-2.5">
          <Sparkles className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold text-foreground">今日焦点</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* 经济日历今日 high */}
          <FocusCard icon={CalendarClock} title="经济日历 · 今日重磅" onMore={() => onNavigate('calendars')} empty={todayHighEvents.length === 0} emptyText="今日无高影响事件">
            {todayHighEvents.map((ev: any, i: number) => (
              <div key={i} className="flex items-start gap-2 py-1.5 border-b border-border/10 last:border-0">
                <span className="mt-1 h-1.5 w-1.5 rounded-full bg-rose-400/70 flex-shrink-0" />
                <div className="min-w-0">
                  <div className="text-xs text-foreground truncate">{ev.title || ev.name}</div>
                  <div className="text-[10px] text-muted-foreground">{ev.country} · {ev.time || ev.date}</div>
                </div>
              </div>
            ))}
          </FocusCard>

          {/* 本周财报前瞻 */}
          <FocusCard icon={BarChart3} title="本周核心财报" onMore={() => onNavigate('calendars')} empty={upcomingEarnings.length === 0} emptyText="暂无临近财报">
            {upcomingEarnings.map((e: any, i: number) => (
              <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/10 last:border-0">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-foreground truncate">{e.ticker}</div>
                  <div className="text-[10px] text-muted-foreground truncate">{e.name}</div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-[10px] text-muted-foreground font-mono">{e.reportDate}</div>
                  <div className="text-[10px] text-amber-400">{e.epsEstimated != null ? `EPS 预期 ${e.epsEstimated}` : ''}</div>
                </div>
              </div>
            ))}
          </FocusCard>

          {/* 资金净流入 Top */}
          <FocusCard icon={ArrowDownUp} title="资金净流入榜" onMore={() => onNavigate('capital')} empty={topInflows.length === 0} emptyText="暂无资金流数据">
            {topInflows.map((c: any, i: number) => (
              <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/10 last:border-0">
                <span className="text-xs text-foreground truncate">{c.label}</span>
                <span className="text-xs font-mono font-bold text-emerald-400">
                  +{(c.amount ?? 0).toLocaleString('en-US', { maximumFractionDigits: 1 })} {c.unit}
                </span>
              </div>
            ))}
          </FocusCard>
        </div>
      </section>
    </div>
  )
}

function FocusCard({
  icon: Icon, title, onMore, empty, emptyText, children,
}: {
  icon: any; title: string; onMore: () => void; empty: boolean; emptyText: string; children: React.ReactNode
}) {
  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col">
      <div className="px-3 py-2 border-b border-border/30 flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">{title}</span>
        <button onClick={onMore} className="ml-auto text-[10px] text-primary hover:underline">更多</button>
      </div>
      <div className="p-3 flex-1">
        {empty ? <div className="text-[11px] text-muted-foreground/70 py-4 text-center">{emptyText}</div> : children}
      </div>
    </div>
  )
}
