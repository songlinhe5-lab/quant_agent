import { useMemo, useState } from 'react'
import { Globe2, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AssetButton } from './shared'
import { MarketSentimentPanel } from './market-sentiment'
import { MacroRiskRadar } from './macro-risk-radar'
import { OptionPcrPanel } from '@/features/options/option-pcr-panel'
import { useDashboardData, type HubTab } from './use-dashboard-data'
import { SegmentTabs, type SegmentItem } from '@/components/ui/data-display/segment-tabs'
import { FocusCard } from './focus-card'

type DashData = ReturnType<typeof useDashboardData>

interface Props {
  data: DashData
  onNavigate: (tab: HubTab, symbol?: string) => void
}

// 前端按 symbol 映射资产类目，供 A 区类目筛选（对齐 Figma 稿类目条，后端 macroAssets 暂未下发 category）。
const ASSET_CATEGORY: Record<string, string> = {
  SPX: '股指', ES: '股指', IXIC: '股指', NQ: '股指', HSI: '股指',
  HSTECH: '股指', N225: '股指', VIX: '股指',
  TNX: '利率',
  'JPY=X': '外汇', 'DX-Y': '外汇', USDCNH: '外汇',
  XAU: '商品', WTI: '商品', HG: '商品',
  BTC: '加密',
  XLK: '行业ETF', XLE: '行业ETF', KWEB: '行业ETF',
}

const CATEGORY_TABS: SegmentItem[] = [
  { value: '全部', label: '全部' },
  { value: '股指', label: '股指' },
  { value: '利率', label: '利率' },
  { value: '外汇', label: '外汇' },
  { value: '商品', label: '商品' },
  { value: '加密', label: '加密' },
  { value: '行业ETF', label: '行业ETF' },
  { value: '类目自定义', label: '类目自定义' },
]

// 经济日历 impact → 星级（对齐 Figma 设计稿：高影响★★★/中★★/低★）
function starsFromImpact(impact: string | undefined): { count: number; cls: string } {
  const k = String(impact || '').toLowerCase()
  if (k === 'high') return { count: 3, cls: 'text-[hsl(var(--bear))]' }
  if (k === 'medium') return { count: 2, cls: 'text-[hsl(var(--warn))]' }
  if (k === 'low') return { count: 1, cls: 'text-slate-500' }
  return { count: 0, cls: 'text-slate-600' }
}

export function OverviewTab({ data, onNavigate }: Props) {
  const [cat, setCat] = useState<string>('全部')

  const vixAsset = useMemo(() => data.assets.find((a: any) => a.symbol === 'VIX') ?? null, [data.assets])

  const filteredAssets = useMemo(() => {
    if (cat === '全部') return data.assets
    return data.assets.filter((a: any) => ASSET_CATEGORY[a.symbol] === cat)
  }, [data.assets, cat])

  // C 区·今日焦点 派生
  // 注意：后端 economicEvents 字段为 impact(非 importance/level)、date 为 UTC ISO
  const todayHighEvents = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    return (data.events || [])
      .filter((ev: any) => String(ev.impact || '').toLowerCase() === 'high')
      .map((ev: any) => ({ ev, day: String(ev.date || ev.time || '').slice(0, 10) }))
      .sort((a: any, b: any) => a.day.localeCompare(b.day))
      // 优先显示今天及之后最近的高影响事件，避免仅因"严格限今天"导致空态
      .filter((x: any) => x.day >= today)
      .slice(0, 4)
      .map((x: any) => x.ev)
  }, [data.events])

  // 注意：earningsCalendar 字段为 date/symbol/name_cn/epsEstimate/epsActual(非 reportDate/ticker/epsEstimated)
  const upcomingEarnings = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    return (data.earnings || [])
      .filter((e: any) => e.date && String(e.date).slice(0, 10) >= today)
      .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
      .slice(0, 4)
  }, [data.earnings])

  // 资金一句话：取最大流入 + 最大流出各 1 条，作为"一句话总结"
  const extremeFlows = useMemo(() => {
    const flows = data.capitalFlows || []
    if (!flows.length) return { maxIn: null, maxOut: null }
    const sorted = [...flows].sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
    const maxIn = sorted[0]
    const maxOut = sorted[sorted.length - 1]
    return {
      maxIn: (maxIn?.amount ?? 0) > 0 ? maxIn : null,
      maxOut: (maxOut?.amount ?? 0) < 0 ? maxOut : null,
    }
  }, [data.capitalFlows])

  return (
    <div className="space-y-5">
      {/* A 区 · 全球市场脉搏 */}
      <section>
        <div className="flex items-center gap-2 mb-2.5">
          <Globe2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-[15px] font-semibold text-foreground">全球市场脉搏</h2>
          <span className="text-[10px] text-muted-foreground/70">跨市场品类首道一入口</span>
          <SegmentTabs
            className="ml-auto"
            items={CATEGORY_TABS}
            value={cat}
            onChange={setCat}
          />
        </div>
        {filteredAssets.length ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
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
          <MarketSentimentPanel vixData={vixAsset} sentimentInd={data.sentimentInd} sentimentHistory={data.sentimentHistory} />
        </div>
        <div className="lg:col-span-1">
          <MacroRiskRadar
            radar={data.radar}
            radarInfo={data.radarInfo}
            setRadarInfo={data.setRadarInfo}
          />
        </div>
        <div className="lg:col-span-1">
          {/* OptionPcrPanel 自带完整面板（标题/数据/图表/footer，对齐 Figma 设计稿） */}
          <OptionPcrPanel />
        </div>
      </section>

      {/* C 区 · 今日焦点 */}
      <section>
        <div className="flex items-center gap-2 mb-2.5">
          <Sparkles className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-[15px] font-semibold text-foreground">今日焦点</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* 经济日历今日 high（后端字段 impact/date/event） */}
          <FocusCard
            title="经济日历 · 今日高影响"
            badge={todayHighEvents.length > 0 ? `×${todayHighEvents.length}` : undefined}
            moreLabel="查看完整日历 →"
            onMore={() => onNavigate('calendars')}
            empty={todayHighEvents.length === 0}
            emptyText="暂无高影响事件"
          >
            {todayHighEvents.map((ev: any, i: number) => {
              const stars = starsFromImpact(ev.impact)
              return (
                <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/10 last:border-0 gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-foreground truncate">{ev.event || ev.name}</div>
                    <div className="text-[10px] text-muted-foreground">{String(ev.date || '').slice(11, 16)} · {ev.country}</div>
                  </div>
                  {stars.count > 0 && (
                    <div className={`flex items-center gap-0.5 text-[10px] ${stars.cls}`} aria-label={`影响度 ${stars.count} 星`}>
                      {Array.from({ length: stars.count }).map((_, k) => (
                        <span key={k}>★</span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </FocusCard>

          {/* 本周财报前瞻（后端字段 date/symbol/name_cn/epsEstimate） */}
          <FocusCard
            title="财报 · 本周"
            badge={upcomingEarnings.length > 0 ? `${upcomingEarnings.length} 家` : undefined}
            moreLabel="查看财报日历 →"
            onMore={() => onNavigate('calendars')}
            empty={upcomingEarnings.length === 0}
            emptyText="暂无临近财报"
          >
            {upcomingEarnings.map((e: any, i: number) => {
              const eps = e.epsEstimate ?? e.eps_estimate ?? null
              return (
                <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/10 last:border-0 gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-semibold text-foreground truncate">{e.symbol} · {e.date?.slice(5, 10) || 'Q2'}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{e.name_cn || e.symbol}</div>
                  </div>
                  <div className={cn(
                    'px-2 py-0.5 rounded text-[11px] font-mono font-bold flex-shrink-0',
                    eps == null
                      ? 'bg-secondary/40 text-muted-foreground'
                      : Number(eps) >= 0
                        ? 'bg-[hsl(var(--bull))]/15 text-[hsl(var(--bull))]'
                        : 'bg-[hsl(var(--bear))]/15 text-[hsl(var(--bear))]'
                  )}>
                    {eps != null ? `$${Number(eps).toFixed(2)}` : '—'}
                  </div>
                </div>
              )
            })}
          </FocusCard>

          {/* 资金一句话：最大流入 + 最大流出 + 趋势说明（对齐 Figma 设计稿） */}
          <FocusCard
            title="资金一句话"
            badge="跨市场"
            moreLabel="资金流向 →"
            onMore={() => onNavigate('capital')}
            empty={!extremeFlows.maxIn && !extremeFlows.maxOut}
            emptyText="暂无资金流数据"
            footerNote={
              extremeFlows.maxIn ? (
                <span>南向连续 3 日净流入，科技板块承压</span>
              ) : undefined
            }
          >
            {extremeFlows.maxIn && (
              <div className="flex items-center justify-between py-1.5 border-b border-border/10">
                <span className="text-xs text-muted-foreground">最大流入</span>
                <span className="text-xs text-foreground">
                  {extremeFlows.maxIn.label}
                  <span className="ml-2 font-mono font-bold text-[hsl(var(--bull))]">
                    +{(extremeFlows.maxIn.amount ?? 0).toLocaleString('en-US', { maximumFractionDigits: 1 })}{extremeFlows.maxIn.unit || ''}
                  </span>
                </span>
              </div>
            )}
            {extremeFlows.maxOut && (
              <div className="flex items-center justify-between py-1.5">
                <span className="text-xs text-muted-foreground">最大流出</span>
                <span className="text-xs text-foreground">
                  {extremeFlows.maxOut.label}
                  <span className="ml-2 font-mono font-bold text-[hsl(var(--bear))]">
                    {(extremeFlows.maxOut.amount ?? 0).toLocaleString('en-US', { maximumFractionDigits: 1 })}{extremeFlows.maxOut.unit || ''}
                  </span>
                </span>
              </div>
            )}
          </FocusCard>
        </div>
      </section>
    </div>
  )
}

// FocusCard 已拆至 ./focus-card (UIRF-15)
