'use client'

import { useState, useEffect, useMemo } from 'react'
import { ShieldAlert, TrendingUp, AlertTriangle, Loader2, Info, X, Activity, PieChart, BarChart3, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Area, AreaChart,
} from 'recharts'
import { useTheme } from 'next-themes'

// ── Types ───────────────────────────────────────────────────────────────

interface KpiData {
  nav: number
  nav_fmt: string
  today_pl: number
  today_pl_fmt: string
  today_pl_pct: number
  cash: number
  cash_fmt: string
  leverage: number
  leverage_fmt: string
  currency: string
}

interface ExposureData { name: string; value: number; pct: number; color: string; lightColor: string }
interface RiskRadarData { axis: string; current: number; limit: number }
interface RiskFactorData { label: string; value: number; threshold: number; unit: string; status: 'safe' | 'warn' | 'good' | 'crit' }
interface NavSnapshot { ts: number; nav: number }
interface PositionData { code: string; stock_name?: string; position_side?: string; qty?: number; market_val?: number; pl_val?: number; pl_ratio?: number; market?: string }

interface AccountDetail {
  kpi: KpiData
  exposure: ExposureData[]
  risk_radar: RiskRadarData[]
  risk_factors: RiskFactorData[]
  nav_snapshots: NavSnapshot[]
  positions: PositionData[]
  currency: string
  position_count: number
}

type AccountsMap = Record<string, AccountDetail>

// ── Constants ───────────────────────────────────────────────────────────────

const MARKET_LABELS: Record<string, { name: string; flag: string; currency: string }> = {
  HK: { name: '港股模拟账户', flag: '🇭🇰', currency: 'HKD' },
  US: { name: '美股模拟账户', flag: '🇺🇸', currency: 'USD' },
}

const statusMeta = {
  safe: { label: '安全', cls: 'text-emerald-500', bg: 'bg-emerald-500/10 border-emerald-500/20', dot: 'bg-emerald-500' },
  warn: { label: '预警', cls: 'text-amber-500', bg: 'bg-amber-500/10 border-amber-500/20', dot: 'bg-amber-500' },
  good: { label: '优秀', cls: 'text-sky-500', bg: 'bg-sky-500/10 border-sky-500/20', dot: 'bg-sky-500' },
  crit: { label: '超限', cls: 'text-red-500', bg: 'bg-red-500/10 border-red-500/20', dot: 'bg-red-500' },
}

const RADAR_HELP = [
  { name: 'Beta', desc: '市场敏感度。>1 波动大于大盘，<1 相对稳健' },
  { name: 'Vol', desc: '年化波动率。60 日日收益率标准差，越高越不稳定' },
  { name: 'Liq', desc: '流动性评分。基于持仓市值与成交量估算变现难度' },
  { name: 'Corr', desc: '持仓相关性。越低分散化越好，过高则风险集中' },
  { name: 'Mom', desc: '动量因子。近期趋势强度，极端值暗示反转风险' },
  { name: 'DD', desc: '最大回撤。NAV 快照序列计算的净值峰值跌幅' },
]

const FACTOR_HELP = [
  { name: 'Market Beta', desc: '组合相对大盘敏感度。=1 同步，>1 波动更大，<1 更防御' },
  { name: 'VaR (95%)', desc: '95% 置信下单日最大预期亏损。60 日历史模拟法' },
  { name: 'Sharpe', desc: '(年化收益 - 无风险利率) / 波动率。>1.5 优秀，<1.0 补偿不足' },
  { name: 'Max DD', desc: '净值峰值到最低点的最大跌幅。极端行情账面亏损幅度' },
]

// ── Sub-components ───────────────────────────────────────────────────────────

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

// ── Account Section ──────────────────────────────────────────────────────────

function AccountSection({ market, account, isDark, loading }: {
  market: string; account: AccountDetail; isDark: boolean; loading: boolean
}) {
  const meta = MARKET_LABELS[market] || { name: market, flag: '🌐', currency: '' }
  const { kpi, exposure, risk_radar, risk_factors, nav_snapshots, positions } = account
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
      {/* ── Account Header ── */}
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

      {/* ── Row 1: KPI Cards (compact inline) ── */}
      <div className="grid grid-cols-3 md:grid-cols-5 gap-1.5">
        {/* NAV */}
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">总净值</p>
          <p className={cn('text-sm font-bold font-mono tabular-nums leading-none', plDir > 0 ? 'text-emerald-500' : 'text-red-500')}>{kpi.nav_fmt}</p>
          <p className={cn('text-[9px] font-mono mt-0.5', plDir > 0 ? 'text-emerald-500/70' : 'text-red-500/70')}>
            {kpi.today_pl >= 0 ? '↑' : '↓'} {kpi.today_pl_fmt} ({kpi.today_pl_pct >= 0 ? '+' : ''}{kpi.today_pl_pct.toFixed(2)}%)
          </p>
        </div>
        {/* Cash */}
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">现金</p>
          <p className="text-sm font-bold font-mono tabular-nums text-foreground">{kpi.cash_fmt}</p>
          <p className="text-[9px] text-muted-foreground mt-0.5">
            {kpi.nav > 0 ? (kpi.cash / kpi.nav * 100).toFixed(1) : '0.0'}%
          </p>
        </div>
        {/* Market Value */}
        <div className="glass-card rounded-lg px-2.5 py-1.5">
          <p className="text-[8px] text-muted-foreground mb-0.5">市值</p>
          <p className="text-sm font-bold font-mono tabular-nums text-foreground">
            {sym}{(positions.reduce((s, p) => s + (p.market_val || 0), 0) / 1000).toFixed(1)}K
          </p>
          <p className="text-[9px] text-muted-foreground mt-0.5">杠杆 {kpi.leverage_fmt}</p>
        </div>
        {/* VaR */}
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
        {/* Sharpe */}
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

      {/* ── Row 2: NAV Curve (compact) ── */}
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
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={navCurve}>
                <defs>
                  <linearGradient id={`navGrad-${market}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={isDark ? '#34d399' : '#059669'} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={isDark ? '#34d399' : '#059669'} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)'} />
                <XAxis dataKey="t" hide />
                <YAxis domain={['auto', 'auto']} hide />
                <Tooltip
                  contentStyle={{ background: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.95)', border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'}`, borderRadius: '8px', fontSize: 11, color: isDark ? '#f8fafc' : '#0f172a', padding: '6px 10px' }}
                  formatter={(v: any) => [`${sym}${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`, 'NAV']}
                />
                <Area type="monotone" dataKey="nav" stroke={isDark ? '#34d399' : '#059669'} strokeWidth={2} fill={`url(#navGrad-${market})`} dot={false} animationDuration={1000} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-[11px] text-muted-foreground">
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {loading ? '加载中...' : '净值数据积累中 (每 5 分钟采样)'}
            </div>
          )}
        </div>
      </div>

      {/* ── Row 3: Risk Radar + Factors + Exposure ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-1.5">
        {/* Risk Score + Radar */}
        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <ShieldAlert className="h-2.5 w-2.5" />雷达
            </span>
            <button onClick={() => setShowRadarHelp(!showRadarHelp)}
              className={cn('transition-colors', showRadarHelp ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>
              <Info className="h-2.5 w-2.5" />
            </button>
          </div>
          {showRadarHelp && <HelpPanel items={RADAR_HELP} onClose={() => setShowRadarHelp(false)} title="六维风险指标" />}
          <div className="flex items-center">
            <RiskScoreGauge radar={risk_radar} isDark={isDark} />
            <div className="flex-1 h-24 pr-0.5">
              {risk_radar.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={risk_radar}>
                    <PolarGrid stroke={isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'} />
                    <PolarAngleAxis dataKey="axis" tick={{ fill: isDark ? 'rgba(156,163,175,0.7)' : 'rgba(100,116,139,0.7)', fontSize: 8 }} />
                    <Radar dataKey="current" stroke={isDark ? '#34d399' : '#059669'} fill={isDark ? '#34d399' : '#059669'} fillOpacity={0.12} strokeWidth={1.5} />
                    <Radar dataKey="limit" stroke={isDark ? 'rgba(239,68,68,0.4)' : 'rgba(220,38,38,0.4)'} fill="none" strokeWidth={1} strokeDasharray="3 2" />
                  </RadarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-[10px] text-muted-foreground">
                  {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : '暂无'}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Factor Monitor */}
        <div className="glass-card rounded-lg overflow-hidden">
          <div className="px-2 py-1 border-b border-border/20 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <BarChart3 className="h-2.5 w-2.5" />因子
            </span>
            <button onClick={() => setShowFactorHelp(!showFactorHelp)}
              className={cn('transition-colors', showFactorHelp ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>
              <Info className="h-2.5 w-2.5" />
            </button>
          </div>
          {showFactorHelp && <HelpPanel items={FACTOR_HELP} onClose={() => setShowFactorHelp(false)} title="风控因子说明" />}
          <div className="divide-y divide-border/10">
            {risk_factors.length > 0 ? risk_factors.map((f, i) => {
              const sm = statusMeta[f.status]
              const pct = f.unit === '%' ? Math.min(Math.abs(f.value) / Math.abs(f.threshold) * 100, 100) : Math.min(Math.abs(f.value) / Math.abs(f.threshold) * 100, 100)
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

        {/* Exposure Breakdown */}
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

      {/* ── Row 4: Positions Table (compact) ── */}
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
    </div>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export function RiskModule() {
  const [isMounted, setIsMounted] = useState(false)
  const [loading, setLoading] = useState(true)
  const { theme } = useTheme()
  const [accounts, setAccounts] = useState<AccountsMap>({})

  useEffect(() => { setIsMounted(true); fetchRiskData() }, [])

  async function fetchRiskData() {
    try {
      setLoading(true)
      const res = await apiClient.get('/risk/dashboard')
      const d = res.data?.data || res.data
      if (d?.accounts) setAccounts(d.accounts)
    } catch (err) {
      console.error('[Risk] 获取风控数据失败:', err)
    } finally {
      setLoading(false)
    }
  }

  if (!isMounted) return null
  const isDark = theme === 'dark'
  const activeMarkets = ['HK', 'US'].filter(m => accounts[m])

  return (
    <div className="space-y-3">
      {activeMarkets.length > 0 ? (
        activeMarkets.map(market => (
          <AccountSection key={market} market={market} account={accounts[market]} isDark={isDark} loading={loading} />
        ))
      ) : (
        <div className="flex items-center justify-center h-32 text-[10px] text-muted-foreground">
          {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
          {loading ? '加载风控数据...' : '暂无账户数据'}
        </div>
      )}
    </div>
  )
}
