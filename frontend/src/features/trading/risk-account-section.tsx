/**
 * 风控账户面板：KPI 卡片 + 净值曲线 + 雷达/因子/敞口 + 持仓表
 */

import { useState, useMemo } from 'react'
import { ShieldAlert, Loader2, Info, X, Activity, PieChart, BarChart3, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { NavAreaChart, RiskRadarChart } from './risk-charts'
import { RiskAdvancedPanel } from './risk-advanced-panel'
import { MARKET_LABELS, statusMeta, RADAR_HELP, FACTOR_HELP } from './risk-types'
import type { AccountDetail, RiskRadarData } from './risk-types'

// ── Small sub-components ──

function HelpPanel({ items, onClose, title }: { items: { name: string; desc: string }[]; onClose: () => void; title: string }) {
  return (
    <div className="px-3 py-2.5 bg-card/80 backdrop-blur-sm border-b border-border/30 space-y-1.5 animate-in fade-in slide-in-from-top-1 duration-200">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-foreground">{title}</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors"><X className="h-3 w-3" /></button>
      </div>
      {items.map(item => (
        <div key={item.name} className="flex items-start gap-2 text-[9px]">
          <span className="font-mono font-bold text-primary min-w-[60px] shrink-0">{item.name}</span>
          <span className="text-muted-foreground leading-relaxed">{item.desc}</span>
        </div>
      ))}
    </div>
  )
}

function RiskScoreGauge({ radar, isDark }: { radar: RiskRadarData[]; isDark: boolean }) {
  const score = useMemo(() => {
    if (!radar.length) return 0
    const avg = radar.reduce((s, d) => s + d.current, 0) / radar.length
    return Math.round(avg)
  }, [radar])

  const color = score >= 70 ? '#ef4444' : score >= 50 ? '#f59e0b' : score >= 30 ? '#3b82f6' : '#10b981'
  const label = score >= 70 ? '高风险' : score >= 50 ? '中高风险' : score >= 30 ? '中等风险' : '低风险'
  const circumference = 2 * Math.PI * 36
  const dash = (score / 100) * circumference

  return (
    <div className="flex flex-col items-center justify-center py-1">
      <div className="relative w-14 h-14">
        <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
          <circle cx="40" cy="40" r="36" fill="none" stroke={isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'} strokeWidth="7" />
          <circle cx="40" cy="40" r="36" fill="none" stroke={color} strokeWidth="7"
            strokeDasharray={`${dash} ${circumference - dash}`} strokeLinecap="round"
            className="transition-all duration-700 ease-out" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-sm font-bold font-mono tabular-nums" style={{ color }}>{score}</span>
          <span className="text-[7px] text-muted-foreground">/100</span>
        </div>
      </div>
      <span className="text-[8px] font-semibold mt-0.5" style={{ color }}>{label}</span>
    </div>
  )
}

// ── Account Section ──

export function AccountSection({ market, account, isDark, loading }: {
  market: string; account: AccountDetail; isDark: boolean; loading: boolean
}) {
  const meta = MARKET_LABELS[market] || { name: market, flag: '🌐', currency: '' }
  const { kpi, exposure, risk_radar, risk_factors, nav_snapshots, positions, correlation } = account
  const [showRadarHelp, setShowRadarHelp] = useState(false)
  const [showFactorHelp, setShowFactorHelp] = useState(false)
  const [positionsExpanded, setPositionsExpanded] = useState(true)
  const sym = kpi.currency === 'HKD' ? 'HK$' : '$'
  const plDir = kpi.today_pl >= 0 ? 1 : -1

  const navCurve = useMemo(() =>
    nav_snapshots.slice().reverse().map((s, i) => ({ t: i, nav: s.nav })),
    [nav_snapshots]
  )

  const totalExposure = exposure.reduce((s, d) => s + d.value, 0)

  return (
    <div className="space-y-1.5">
      {/* Account Header */}
      <div className="flex items-center justify-between py-0.5">
        <div className="flex items-center gap-1.5">
          <span className="text-sm">{meta.flag}</span>
          <span className="text-xs font-bold text-foreground">{meta.name}</span>
          <span className="text-[9px] text-muted-foreground font-mono bg-muted/50 px-1 py-0.5 rounded">{kpi.currency}</span>
        </div>
        <div className="flex items-center gap-2 text-[9px] text-muted-foreground">
          <span>{positions.length} 只</span>
          <span className="flex items-center gap-1">
            <span className={cn('h-1 w-1 rounded-full', plDir >= 0 ? 'bg-emerald-500' : 'bg-red-500')} />
            {kpi.today_pl_pct >= 0 ? '+' : ''}{kpi.today_pl_pct.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-3 md:grid-cols-5 gap-1.5">
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">总净值</p>
          <p className={cn('text-sm font-bold font-mono tabular-nums leading-none', plDir > 0 ? 'text-emerald-500' : 'text-red-500')}>{kpi.nav_fmt}</p>
          <p className={cn('text-[9px] font-mono mt-0.5', plDir > 0 ? 'text-emerald-500/70' : 'text-red-500/70')}>
            {kpi.today_pl >= 0 ? '↑' : '↓'} {kpi.today_pl_fmt} ({kpi.today_pl_pct >= 0 ? '+' : ''}{kpi.today_pl_pct.toFixed(2)}%)
          </p>
        </div>
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">现金</p>
          <p className="text-sm font-bold font-mono tabular-nums text-foreground">{kpi.cash_fmt}</p>
          <p className="text-[9px] text-muted-foreground mt-0.5">{kpi.nav > 0 ? (kpi.cash / kpi.nav * 100).toFixed(1) : '0.0'}%</p>
        </div>
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">市值</p>
          <p className="text-sm font-bold font-mono tabular-nums text-foreground">
            {sym}{(positions.reduce((s, p) => s + (p.market_val || 0), 0) / 1000).toFixed(1)}K
          </p>
          <p className="text-[9px] text-muted-foreground mt-0.5">杠杆 {kpi.leverage_fmt}</p>
        </div>
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">VaR 95%</p>
          {(() => {
            const varFactor = risk_factors.find(f => f.label === 'VaR (95%)')
            if (!varFactor) return <p className="text-sm font-bold font-mono text-muted-foreground">--</p>
            const sm = statusMeta[varFactor.status]
            return (
              <>
                <p className={cn('text-sm font-bold font-mono tabular-nums', sm.cls)}>${Math.abs(varFactor.value).toLocaleString()}</p>
                <p className={cn('text-[9px] mt-0.5', sm.cls, 'opacity-70')}>单日最大预期亏损</p>
              </>
            )
          })()}
        </div>
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">Sharpe</p>
          {(() => {
            const sharpeFactor = risk_factors.find(f => f.label === 'Sharpe')
            if (!sharpeFactor) return <p className="text-sm font-bold font-mono text-muted-foreground">--</p>
            const sm = statusMeta[sharpeFactor.status]
            return (
              <>
                <p className={cn('text-sm font-bold font-mono tabular-nums', sm.cls)}>{sharpeFactor.value.toFixed(2)}</p>
                <p className={cn('text-[9px] mt-0.5', sm.cls, 'opacity-70')}>风险调整收益</p>
              </>
            )
          })()}
        </div>
      </div>

      {/* NAV Curve */}
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="px-3 py-1 border-b border-border/20 flex items-center justify-between">
          <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
            <Activity className="h-2.5 w-2.5" />净值
          </span>
          <span className="text-[8px] text-muted-foreground font-mono">
            {nav_snapshots.length > 0 ? `${nav_snapshots.length} 快照` : '等待积累'}
          </span>
        </div>
        <div className="p-1.5 h-28">
          {navCurve.length > 1 ? (
            <NavAreaChart data={navCurve} currencySym={sym} />
          ) : (
            <div className="h-full flex items-center justify-center text-[11px] text-muted-foreground">
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {loading ? '加载中...' : '净值数据积累中 (每 5 分钟采样)'}
            </div>
          )}
        </div>
      </div>

      {/* Risk Radar + Factors + Exposure */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-1.5">
        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <ShieldAlert className="h-2.5 w-2.5" />雷达
            </span>
            <button onClick={() => setShowRadarHelp(!showRadarHelp)} className={cn('transition-colors', showRadarHelp ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>
              <Info className="h-2.5 w-2.5" />
            </button>
          </div>
          {showRadarHelp && <HelpPanel items={RADAR_HELP} onClose={() => setShowRadarHelp(false)} title="六维风险指标" />}
          <div className="flex items-center">
            <RiskScoreGauge radar={risk_radar} isDark={isDark} />
            <div className="flex-1 h-24 pr-0.5">
              {risk_radar.length > 0 ? (
                <RiskRadarChart data={risk_radar} />
              ) : (
                <div className="h-full flex items-center justify-center text-[10px] text-muted-foreground">
                  {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : '暂无'}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <BarChart3 className="h-2.5 w-2.5" />因子
            </span>
            <button onClick={() => setShowFactorHelp(!showFactorHelp)} className={cn('transition-colors', showFactorHelp ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>
              <Info className="h-2.5 w-2.5" />
            </button>
          </div>
          {showFactorHelp && <HelpPanel items={FACTOR_HELP} onClose={() => setShowFactorHelp(false)} title="风控因子说明" />}
          <div className="divide-y divide-border/10">
            {risk_factors.length > 0 ? risk_factors.map((f, i) => {
              const sm = statusMeta[f.status]
              const pct = Math.min(Math.abs(f.value) / Math.abs(f.threshold) * 100, 100)
              return (
                <div key={i} className="px-2 py-1">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-[9px] font-semibold">{f.label}</span>
                    <div className="flex items-center gap-1">
                      <span className={cn('text-[9px] font-mono font-bold tabular-nums', sm.cls)}>
                        {f.unit === '$' ? `$${Math.abs(f.value).toLocaleString()}` : `${f.value}${f.unit}`}
                      </span>
                      <span className={cn('text-[7px] px-0.5 py-px rounded border font-bold', sm.bg, sm.cls)}>{sm.label}</span>
                    </div>
                  </div>
                  <div className="h-0.5 bg-muted/30 rounded-full overflow-hidden">
                    <div className={cn('h-full rounded-full transition-all duration-500', sm.dot)} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            }) : (
              <div className="px-2 py-4 text-center text-[9px] text-muted-foreground">
                {loading ? <Loader2 className="h-3 w-3 animate-spin mx-auto" /> : '暂无'}
              </div>
            )}
          </div>
        </div>

        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-2 py-1 border-b border-border/20">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <PieChart className="h-2.5 w-2.5" />敞口
            </span>
          </div>
          <div className="p-1.5 space-y-1">
            {exposure.map((d) => {
              const barPct = totalExposure > 0 ? (d.value / totalExposure) * 100 : 0
              return (
                <div key={d.name}>
                  <div className="flex items-center justify-between mb-0.5">
                    <div className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: isDark ? d.color : d.lightColor }} />
                      <span className="text-[9px] font-medium">{d.name}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[9px]">
                      <span className="font-mono font-bold tabular-nums">{d.pct}%</span>
                      <span className="text-muted-foreground font-mono tabular-nums text-[8px]">{sym}{(d.value / 1000).toFixed(1)}K</span>
                    </div>
                  </div>
                  <div className="h-1 bg-muted/20 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${barPct}%`, background: isDark ? d.color : d.lightColor }} />
                  </div>
                </div>
              )
            })}
            {exposure.length === 0 && (
              <div className="py-2 text-center text-[9px] text-muted-foreground">暂无持仓</div>
            )}
          </div>
        </div>
      </div>

      {/* Positions Table */}
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="px-3 py-1 border-b border-border/20 flex items-center justify-between cursor-pointer" onClick={() => setPositionsExpanded(!positionsExpanded)}>
          <span className="text-[9px] font-semibold text-muted-foreground uppercase">持仓</span>
          <div className="flex items-center gap-1.5 text-[9px] text-muted-foreground">
            <span>{positions.length} 只</span>
            {positionsExpanded ? <ChevronUp className="h-2.5 w-2.5" /> : <ChevronDown className="h-2.5 w-2.5" />}
          </div>
        </div>
        {positionsExpanded && (
          <div className="overflow-auto">
            {positions.length > 0 ? (
              <table className="w-full text-[9px]">
                <thead className="sticky top-0 bg-card/90 backdrop-blur-sm">
                  <tr className="text-muted-foreground border-b border-border/20">
                    <th className="text-left px-3 py-1 font-medium">代码</th>
                    <th className="text-left px-2 py-1 font-medium">名称</th>
                    <th className="text-center px-2 py-1 font-medium">方向</th>
                    <th className="text-right px-2 py-1 font-medium">数量</th>
                    <th className="text-right px-2 py-1 font-medium">市值</th>
                    <th className="text-right px-2 py-1 font-medium">盈亏</th>
                    <th className="text-right px-2 py-1 font-medium">盈亏%</th>
                    <th className="text-right px-3 py-1 font-medium">占比</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, i) => {
                    const mv = p.market_val || 0
                    const pl = p.pl_val || 0
                    const plR = p.pl_ratio || 0
                    const navPct = kpi.nav > 0 ? (mv / kpi.nav * 100) : 0
                    return (
                      <tr key={i} className="border-b border-border/5 hover:bg-muted/20 transition-colors">
                        <td className="px-3 py-1 font-mono font-semibold">{p.code}</td>
                        <td className="px-2 py-1 text-muted-foreground truncate max-w-[80px]">{p.stock_name || '-'}</td>
                        <td className="px-2 py-1 text-center">
                          <span className={cn('text-[8px] px-1 py-px rounded font-bold',
                            p.position_side === 'LONG' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'
                          )}>{p.position_side === 'LONG' ? '多' : '空'}</span>
                        </td>
                        <td className="px-2 py-1 text-right font-mono tabular-nums">{(p.qty || 0).toLocaleString()}</td>
                        <td className="px-2 py-1 text-right font-mono tabular-nums">{sym}{(mv / 1000).toFixed(1)}K</td>
                        <td className={cn('px-2 py-1 text-right font-mono tabular-nums', pl >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                          {pl >= 0 ? '+' : ''}{sym}{Math.abs(pl).toFixed(0)}
                        </td>
                        <td className={cn('px-2 py-1 text-right font-mono tabular-nums', plR >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                          {plR >= 0 ? '+' : ''}{plR.toFixed(2)}%
                        </td>
                        <td className="px-3 py-1 text-right font-mono tabular-nums text-muted-foreground">{navPct.toFixed(1)}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-4 text-center text-[9px] text-muted-foreground">
                {loading ? <Loader2 className="h-3 w-3 animate-spin mx-auto mb-1" /> : null}
                {loading ? '加载中...' : '暂无持仓'}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Advanced Risk Panel */}
      <RiskAdvancedPanel market={market} correlation={correlation} />
    </div>
  )
}
