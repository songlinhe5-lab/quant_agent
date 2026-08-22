/**
 * 风控账户面板：KPI 卡片 + 净值曲线 + 雷达/因子/敞口 + 持仓表
 */

import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldAlert, Loader2, Info, X, Activity, PieChart, BarChart3, ChevronDown, ChevronUp, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RISK_COLORS } from '@/lib/constants'
import { NavAreaChart, RiskRadarChart } from './risk-charts'
import { RiskAdvancedPanel } from './risk-advanced-panel'
import { RiskAttributionPanel } from './risk-attribution-panel'
import { MARKET_LABELS, statusMeta, RADAR_HELP, FACTOR_HELP, riskLevelOf } from './risk-types'
import type { AccountDetail, RiskRadarData, PositionData } from './risk-types'
import { HelpPanel, RiskScoreGauge } from '@/features/risk/risk-sub-components'

// ── Small sub-components ──

// ── Account Section ──

export function AccountSection({ market, account, isDark, loading }: {
  market: string; account: AccountDetail; isDark: boolean; loading: boolean
}) {
  const meta = MARKET_LABELS[market] || { name: market, flag: '🌐', currency: '' }
  const { kpi, exposure, risk_radar, risk_factors, nav_snapshots, positions, correlation } = account
  const [showRadarHelp, setShowRadarHelp] = useState(false)
  const [showFactorHelp, setShowFactorHelp] = useState(false)
  const [positionsExpanded, setPositionsExpanded] = useState(true)
  const [riskTab, setRiskTab] = useState<'overview' | 'factor' | 'stress'>('overview')
  const navigate = useNavigate()
  // STRAT: 持仓表排序 (列 + 方向), 无排序时保持原始顺序
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const sym = kpi.currency === 'HKD' ? 'HK$' : '$'
  const plDir = kpi.today_pl >= 0 ? 1 : -1

  const navCurve = useMemo(() =>
    nav_snapshots.slice().reverse().map((s, i) => ({ t: i, nav: s.nav })),
    [nav_snapshots]
  )

  // STRAT: 持仓排序 + 合计
  const sortedPositions = useMemo(() => {
    if (!sortKey || sortKey === 'code') return positions
    const dir = sortDir === 'asc' ? 1 : -1
    return [...positions].sort((a, b) => {
      const av = a[sortKey as keyof PositionData] ?? 0
      const bv = b[sortKey as keyof PositionData] ?? 0
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }, [positions, sortKey, sortDir])

  const totalMarketVal = useMemo(() => positions.reduce((s, p) => s + (p.market_val || 0), 0), [positions])
  const totalPl = useMemo(() => positions.reduce((s, p) => s + (p.pl_val || 0), 0), [positions])
  const totalNavPct = kpi.nav > 0 ? totalMarketVal / kpi.nav * 100 : 0

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const SortIcon = ({ col }: { col: string }) => {
    if (sortKey !== col) return <ArrowUpDown className="h-2.5 w-2.5 inline ml-0.5 opacity-40" />
    return sortDir === 'asc' ? <ArrowUp className="h-2.5 w-2.5 inline ml-0.5 text-primary" /> : <ArrowDown className="h-2.5 w-2.5 inline ml-0.5 text-primary" />
  }

  // STRAT: 脏名启发式标注 (透传 Futu 名称, 不做前端臆测纠错)
  // 仅当名称含替换符/控制字符/明显乱码时才标注"以交易所为准"
  const isDirtyName = (name?: string) => {
    if (!name) return false
    // 含替换符 U+FFFD / 控制字符 / 英文混杂中文时的异常空格 (如 "闽文 集团" 前导空格)
    return /[\uFFFD]|[\u0000-\u001F\u007F]/.test(name) || /^\s|[\s]{2,}/.test(name)
  }

  const totalExposure = exposure.reduce((s, d) => s + d.value, 0)
  const topConcentration = exposure.reduce((m, d) => Math.max(m, d.pct), 0)

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
          <p className="text-[8px] text-muted-foreground mb-0.5">VaR 95% <span className="text-[7px] px-0.5 rounded bg-sky-500/10 text-sky-500">双口径</span></p>
          {(() => {
            const varFactor = risk_factors.find(f => f.label === 'VaR (95%)')
            if (!varFactor) return <p className="text-sm font-bold font-mono text-muted-foreground">--</p>
            const sm = statusMeta[varFactor.status]
            const hasAmount = typeof (varFactor as any).amount === 'number'
            // 旧固定量纲 (无 amount 字段) → 打占位, 不展示误导数字
            if (!hasAmount || varFactor.value === 0) {
              return <p className="text-sm font-bold font-mono text-amber-500">口径修正中</p>
            }
            const amount = Math.abs((varFactor as any).amount)
            return (
              <>
                <p className={cn('text-sm font-bold font-mono tabular-nums', sm.cls)}>
                  {sym}{amount.toLocaleString()}<span className="text-[10px] text-muted-foreground font-semibold"> · {varFactor.value}%</span>
                </p>
                <p className={cn('text-[9px] mt-0.5', sm.cls, 'opacity-70')}>金额 · 日收益 5 分位 × 当前净值</p>
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
          <span className="text-[8px] text-muted-foreground font-mono" title="NAV 守护进程每 300 秒采样, Redis ltrim 保留 288 条">
            {nav_snapshots.length > 0 ? `${nav_snapshots.length} 快照 · 每 5 分钟采样` : '等待积累'}
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

      {/* ── PROD-06: 风控面板 Tab 分组（概览/因子/压测），解决 7 图表平铺一屏放不下 ── */}
      <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm w-fit">
        {([['overview', '概览', Activity], ['factor', '因子', BarChart3], ['stress', '压测', ShieldAlert]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setRiskTab(id)} className={cn('text-[10px] px-2.5 py-1 rounded flex items-center gap-1 transition-colors',
            riskTab === id ? 'bg-primary text-primary-foreground shadow-sm shadow-primary/30' : 'text-muted-foreground hover:text-foreground')}>
            <Icon className="h-3 w-3" />{label}
          </button>
        ))}
      </div>

      {riskTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-1.5">
          {/* Radar */}
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

          {/* Exposure + 集中度 */}
          <div className="glass-card rounded-lg overflow-hidden md:col-span-2">
            <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
              <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
                <PieChart className="h-2.5 w-2.5" />敞口 / 集中度
              </span>
              <span className="text-[8px] text-muted-foreground font-mono">集中度(Top1) {topConcentration.toFixed(1)}%</span>
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
      )}

      {riskTab === 'factor' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-1.5">
          {/* Factor list */}
          <div className="glass-card rounded-lg overflow-hidden">
            <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
              <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
                <BarChart3 className="h-2.5 w-2.5" />风险因子阈值
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
                          {f.unit === '%' ? `${f.value}%` : f.unit === '$' ? `$${Math.abs(f.value).toLocaleString()}` : `${f.value}${f.unit}`}
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

          {/* Jensen 归因 + 板块/相关性 */}
          <div className="md:col-span-2 space-y-1.5">
            <RiskAttributionPanel market={market} />
            <RiskAdvancedPanel market={market} correlation={correlation} tabs={['sector', 'corr']} />
          </div>
        </div>
      )}

      {riskTab === 'stress' && (
        <div className="space-y-1.5">
          <div className="px-2.5 py-1.5 rounded-md bg-amber-500/5 border border-amber-500/20 text-[9px] text-amber-600/90 dark:text-amber-400/90">
            ⚠ 口径明示: 历史情景 (2008/2020/2022) 采用<b>预设 shock / 板块冲击系数</b>, 并非真实历史 K 线回放
          </div>
          <RiskAdvancedPanel market={market} correlation={correlation} tabs={['cvar', 'stress']} />
        </div>
      )}

      {/* Positions Table — STRAT: 排序 / 行下钻 / 合计校验 / 脏名标注 */}
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="px-3 py-1 border-b border-border/20 flex items-center justify-between cursor-pointer" onClick={() => setPositionsExpanded(!positionsExpanded)}>
          <span className="text-[9px] font-semibold text-muted-foreground uppercase">持仓明细</span>
          <div className="flex items-center gap-1.5 text-[9px] text-muted-foreground">
            <span>点击表头排序 · 行点击下钻</span>
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
                    <th className="text-right px-2 py-1 font-medium cursor-pointer select-none" onClick={() => toggleSort('qty')}>数量 <SortIcon col="qty" /></th>
                    <th className="text-right px-2 py-1 font-medium cursor-pointer select-none" onClick={() => toggleSort('market_val')}>市值 <SortIcon col="market_val" /></th>
                    <th className="text-right px-2 py-1 font-medium cursor-pointer select-none" onClick={() => toggleSort('pl_val')}>盈亏 <SortIcon col="pl_val" /></th>
                    <th className="text-right px-2 py-1 font-medium cursor-pointer select-none" onClick={() => toggleSort('pl_ratio')}>盈亏% <SortIcon col="pl_ratio" /></th>
                    <th className="text-right px-3 py-1 font-medium">占比</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedPositions.map((p, i) => {
                    const mv = p.market_val || 0
                    const pl = p.pl_val || 0
                    const plR = p.pl_ratio || 0
                    const navPct = kpi.nav > 0 ? (mv / kpi.nav * 100) : 0
                    const dirty = isDirtyName(p.stock_name)
                    return (
                      <tr
                        key={i}
                        onClick={() => navigate(`/market/${encodeURIComponent(p.code)}`)}
                        className="border-b border-border/5 hover:bg-blue-500/5 transition-colors cursor-pointer"
                        title={`点击下钻 ${p.code}`}
                      >
                        <td className="px-3 py-1 font-mono font-semibold">{p.code}</td>
                        <td className="px-2 py-1 text-muted-foreground truncate max-w-[100px]">
                          <span className="inline-flex items-center gap-1">
                            {p.stock_name || '-'}
                            {dirty && <span className="text-[7px] px-1 py-px rounded bg-amber-500/10 text-amber-500 whitespace-nowrap">数据源名称·以交易所为准</span>}
                          </span>
                        </td>
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
                  {/* 合计行 + 占比校验 */}
                  <tr className="bg-muted/30 border-t border-border/40 font-semibold text-foreground">
                    <td colSpan={4} className="px-3 py-1 text-[9px] text-muted-foreground">合计 · 占比校验 (分母 = nav)</td>
                    <td className="px-2 py-1 text-right font-mono tabular-nums">{sym}{(totalMarketVal / 1000).toFixed(1)}K</td>
                    <td className={cn('px-2 py-1 text-right font-mono tabular-nums', totalPl >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                      {totalPl >= 0 ? '+' : ''}{sym}{Math.abs(totalPl).toFixed(0)}
                    </td>
                    <td className={cn('px-2 py-1 text-right font-mono tabular-nums', totalPl >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                      {totalPl >= 0 ? '+' : ''}{(kpi.nav > 0 ? totalPl / kpi.nav * 100 : 0).toFixed(2)}%
                    </td>
                    <td className="px-3 py-1 text-right font-mono tabular-nums">
                      <span className={cn(Math.abs(totalNavPct - 100) < 5 ? 'text-emerald-500' : 'text-amber-500')}>
                        {totalNavPct.toFixed(1)}% {Math.abs(totalNavPct - 100) < 5 ? '✓' : '⚠'}
                      </span>
                    </td>
                  </tr>
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
    </div>
  )
}
