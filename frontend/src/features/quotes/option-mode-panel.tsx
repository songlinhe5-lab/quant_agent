import { useMemo, useState } from 'react'
import { Grid2X2, Box, Target, Activity, FlaskConical, Database, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import { OptionVolSurface } from '@/features/options/option-vol-surface'
import { OptionVolSurface3D } from '@/features/options/option-vol-surface-3d'
import { OptionStrategyLabPanel } from '@/features/options/option-strategy-lab-panel'
import { OptionVolatilityPanel } from '@/features/options/option-volatility-panel'
import { toMarketSymbol } from './symbol-utils'
import { useOptionIvSummary } from './use-option-iv-summary'

/**
 * 个股工作台 · 中列 [K线|期权] 的「期权」模式。
 * 迁入自 options 模块，以自选池选中标的为参数（Figma Frame 5 中列期权模式）。
 * - 顶部：视图切换 + IV 指标条（ATM IV / IV 分位 / 30日已实现 / Skew）
 * - [IV热力图 | 3D曲面] 切换
 * - 热力图点选合约 → 联动下方 Greeks（OptionVolatilityPanel）
 * - 底部联动卡片：损益实验室 + Greeks · 选中合约 + 数据源标签
 */
export function OptionModePanel({ symbol }: { symbol: string }) {
  const futu = useMemo(() => toMarketSymbol(symbol), [symbol])
  const [view, setView] = useState<'2d' | '3d'>('2d')
  const [leg, setLeg] = useState<{ type: string; expiry: string; strike: number } | null>(null)

  const ivSummary = useOptionIvSummary(futu)

  const occ = useMemo(() => {
    if (!leg || !futu.includes('.')) return null
    const [mkt, root] = futu.split('.')
    const yymmdd = leg.expiry.replace(/-/g, '').slice(2)
    const strike6 = String(Math.round(leg.strike * 1000)).padStart(6, '0')
    return `${mkt}.${root}${yymmdd}${leg.type === 'call' ? 'C' : 'P'}${strike6}`
  }, [leg, futu])

  const ivMetrics = [
    { label: 'ATM IV', value: ivSummary?.atmIv != null ? `${(ivSummary.atmIv * 100).toFixed(1)}%` : '--', tone: 'text-violet-300' },
    { label: 'IV 分位', value: ivSummary?.ivPercentile != null ? `${(ivSummary.ivPercentile * 100).toFixed(0)}%` : '--', tone: 'text-sky-300' },
    { label: '30日已实现', value: ivSummary?.rv30d != null ? `${(ivSummary.rv30d * 100).toFixed(1)}%` : '--', tone: 'text-emerald-300' },
    { label: 'Skew', value: ivSummary?.skew != null ? `${ivSummary.skew >= 0 ? '+' : ''}${ivSummary.skew.toFixed(1)}` : '--', tone: 'text-amber-300' },
  ]

  return (
    <div className="flex flex-col gap-3 overflow-y-auto custom-scrollbar p-2">
      {/* 顶部：视图切换 + 摘要条 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-border/60 p-0.5">
          {(
            [
              { id: '2d', label: 'IV 热力图', icon: Grid2X2 },
              { id: '3d', label: '3D 曲面', icon: Box },
            ] as const
          ).map((v) => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors',
                view === v.id ? 'bg-primary text-primary-foreground' : 'text-slate-400 hover:text-slate-200',
              )}
            >
              <v.icon className="h-3.5 w-3.5" />
              {v.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-400">
          <Target className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="font-mono">{futu}</span>
        </div>
      </div>

      {/* IV 指标条（设计稿：ATM IV / IV 分位 / 30日已实现 / Skew） */}
      <div className="grid grid-cols-4 gap-1.5">
        {ivMetrics.map((m) => (
          <div key={m.label} className="rounded-lg border border-border/40 bg-card/40 px-2 py-1.5 text-center">
            <div className="text-[9px] text-slate-500">{m.label}</div>
            <div className={cn('text-sm font-semibold font-mono', m.tone)}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* 主体：热力图 / 3D 曲面 */}
      <div className="glass-card rounded-lg overflow-hidden">
        {view === '2d' ? (
          <OptionVolSurface symbol={futu} onSelectContract={(l) => setLeg({ ...l })} />
        ) : (
          <div className="p-2">
            <OptionVolSurface3D symbol={futu} />
          </div>
        )}
      </div>

      {/* 底部联动卡片：损益实验室 + Greeks · 选中合约 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 损益实验室 */}
        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-border/30 flex items-center gap-2">
            <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">损益实验室</span>
          </div>
          <OptionStrategyLabPanel ticker={futu} />
        </div>

        {/* Greeks · 选中合约 */}
        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-border/30 flex items-center gap-2">
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Greeks</span>
            {occ && (
              <span className="ml-auto font-mono text-[10px] text-slate-500 truncate">{occ}</span>
            )}
          </div>
          <OptionVolatilityPanel ticker={occ || ''} />
        </div>
      </div>

      {/* 数据源标签（设计稿底部联动卡片） */}
      <div className="flex flex-wrap items-center gap-1.5 px-1">
        <span className="text-[9px] text-muted-foreground/70 inline-flex items-center gap-1">
          <Database className="h-3 w-3" /> 数据源
        </span>
        {['market/option-strategy-lab', 'market/option-volatility', 'Futu OpenD', 'PixUi v8'].map((s) => (
          <span key={s} className="text-[9px] font-mono text-slate-400 border border-border/40 rounded px-1.5 py-0.5 bg-card/30 inline-flex items-center gap-1">
            {s === 'Futu OpenD' && <Zap className="h-2.5 w-2.5 text-amber-400" />}
            {s}
          </span>
        ))}
      </div>
    </div>
  )
}
