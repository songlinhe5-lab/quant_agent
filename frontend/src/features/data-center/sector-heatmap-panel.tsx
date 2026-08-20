import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface HeatMapData {
  market?: string
  breadth_ratio?: number
  avg_change?: number
  sentiment?: string
  up?: number
  down?: number
  flat?: number
  top_gainers?: { name: string; code?: string; change: number }[]
  top_losers?: { name: string; code?: string; change: number }[]
  sector_summary?: { sector: string; avg_change: number }[]
  updated_at?: string
  source?: string
  note?: string
  degraded?: boolean
  degraded_message?: string
}

function toneBg(chg: number): string {
  if (chg >= 3) return 'bg-[hsl(var(--bull))]/30 border-[hsl(var(--bull))]/50'
  if (chg >= 1) return 'bg-[hsl(var(--bull))]/15 border-[hsl(var(--bull))]/30'
  if (chg > 0) return 'bg-[hsl(var(--bull))]/5 border-[hsl(var(--bull))]/20'
  if (chg <= -3) return 'bg-[hsl(var(--bear))]/30 border-[hsl(var(--bear))]/50'
  if (chg <= -1) return 'bg-[hsl(var(--bear))]/15 border-[hsl(var(--bear))]/30'
  return 'bg-[hsl(var(--bear))]/5 border-[hsl(var(--bear))]/20'
}

// 单一板块背景色（按涨跌幅返回对应背景，无边框），用于设计稿横向条带
function heatColor(chg: number): string {
  if (chg >= 3) return 'bg-[hsl(var(--bull))]/70'
  if (chg >= 1.5) return 'bg-[hsl(var(--bull))]/55'
  if (chg >= 0.5) return 'bg-[hsl(var(--bull))]/40'
  if (chg > 0) return 'bg-[hsl(var(--bull))]/25'
  if (chg === 0) return 'bg-slate-500/40'
  if (chg > -0.5) return 'bg-[hsl(var(--bear))]/25'
  if (chg > -1.5) return 'bg-[hsl(var(--bear))]/40'
  if (chg > -3) return 'bg-[hsl(var(--bear))]/55'
  return 'bg-[hsl(var(--bear))]/70'
}

function sentimentTone(s?: string): string {
  if (s === 'risk_on') return 'text-emerald-400'
  if (s === 'risk_off') return 'text-red-400'
  return 'text-amber-400'
}

export function SectorHeatmapPanel({ market = 'HK' }: { market?: string }) {
  const [data, setData] = useState<HeatMapData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: HeatMapData }>(`/market/heat-map/${market}`)
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [market])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载板块热力图 ({market})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        板块热力图暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无板块热力图数据</div>

  const sectors = data.sector_summary || []
  const gainers = data.top_gainers || []
  const losers = data.top_losers || []

  // 后端 degraded / 空数据时给出明确提示，而非静默空
  if (sectors.length === 0 && gainers.length === 0 && losers.length === 0) {
    return (
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">板块热力图</span>
          <span className="font-mono text-xs text-foreground/80">{data.market || market}</span>
        </div>
        <div className="p-6 text-sm text-amber-400/90">
          板块热力图数据暂不可用
          <span className="ml-1 text-[10px] text-amber-400/60">· {data.degraded_message || '数据源（Futu 板块快照）暂未返回数据，恢复后自动重试'}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      {/* 标题区：紧凑摘要 + 右上领涨/领跌（对齐 Figma 设计稿） */}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">板块热力图</span>
        <span className="font-mono text-[10px] text-foreground/80 ml-1">
          {data.market || market} · 涨 {data.up ?? '--'} · 平 {data.flat ?? '--'} · 跌 {data.down ?? '--'}
        </span>
        {/* 右上领涨/领跌摘要 */}
        <span className="ml-auto text-[10px] font-mono">
          {gainers[0] && (
            <span className="text-[hsl(var(--bull))] dark:text-[hsl(var(--bull))]">
              领涨 {gainers[0].name} +{gainers[0].change.toFixed(2)}%
            </span>
          )}
          {gainers[0] && losers[0] && <span className="mx-1 text-muted-foreground/60">·</span>}
          {losers[0] && (
            <span className="text-[hsl(var(--bear))] dark:text-[hsl(var(--bear))]">
              领跌 {losers[0].name} {losers[0].change >= 0 ? '+' : ''}{losers[0].change.toFixed(2)}%
            </span>
          )}
        </span>
      </div>

      <div className="p-3 space-y-3">
        {/* 顶部：横向连续热力条带（按 avg_change 排序着色） */}
        {sectors.length > 0 && (
          <div className="flex h-2 w-full rounded overflow-hidden">
            {[...sectors]
              .sort((a, b) => b.avg_change - a.avg_change)
              .map((s, i) => (
                <div
                  key={i}
                  className={heatColor(s.avg_change) + ' flex-1'}
                  title={`${s.sector} ${s.avg_change >= 0 ? '+' : ''}${s.avg_change.toFixed(2)}%`}
                />
              ))}
          </div>
        )}

        {/* 下方：板块方块（自适应列数，显示不下自动折行；窄容器不再硬挤 8 列导致截断） */}
        <div className="flex flex-wrap gap-1.5">
          {sectors.map((s, i) => (
            <div
              key={i}
              className={
                'flex flex-col items-center justify-center py-2 px-1.5 rounded border ' +
                toneBg(s.avg_change) +
                ' flex-1 min-w-[64px] max-w-[12.5%]'
              }
              title={`${s.sector} ${s.avg_change >= 0 ? '+' : ''}${s.avg_change.toFixed(2)}%`}
            >
              <div className="text-[11px] font-semibold text-foreground truncate w-full text-center">{s.sector}</div>
              <div className="text-[10px] font-mono mt-0.5">
                {s.avg_change >= 0 ? '+' : ''}{s.avg_change.toFixed(2)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 底部 footer（对齐设计稿：左数据源 / 右更新于实时） */}
      <div className="px-4 py-1.5 border-t border-border/20 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>数据源:{data.source || 'Futu'}</span>
        <span className="flex items-center gap-1.5">
          更新于
          <span className="font-bold text-[hsl(var(--bull))] dark:text-[hsl(var(--bull))]">实时</span>
        </span>
      </div>
    </div>
  )
}
