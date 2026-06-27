'use client'

import { useState, useEffect } from 'react'
import { ShieldAlert, TrendingUp, Bell, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid, BarChart, Bar, Cell } from 'recharts'
import { useTheme } from 'next-themes'

// ── Mock Data ───────────────────────────────────────────────────────────────

const portfolioKpi = [
  { label: '总净值 (NAV)', value: '$245,678.90', pct: '+5.28%', dir: 1 },
  { label: '今日盈亏 P&L', value: '+$3,421.50', pct: '+0.49%', dir: 1 },
  { label: '可用保证金', value: '$125,432.10', pct: '-1.65%', dir: -1 },
  { label: '杠杆利用率', value: '48.9%', pct: '80%限', dir: 0 },
]

const exposureData = [
  { name: '多头', value: 145000, pct: 59.1, color: '#34d399', lightColor: '#059669' },
  { name: '空头', value: 98000, pct: 39.9, color: '#f87171', lightColor: '#dc2626' },
  { name: '现金', value: 2678, pct: 1.1, color: '#f59e0b', lightColor: '#d97706' },
]

const riskRadar = [
  { axis: 'Beta', current: 85, limit: 100 },
  { axis: 'Vol', current: 45, limit: 70 },
  { axis: 'Liq', current: 72, limit: 60 },
  { axis: 'Corr', current: 58, limit: 80 },
  { axis: 'Mom', current: 81, limit: 75 },
  { axis: 'DD', current: 57, limit: 80 },
]

const riskFactors = [
  { label: 'Market Beta', value: 0.85, threshold: 1.0, unit: '', status: 'safe' as const },
  { label: 'VaR (95%)', value: -2456, threshold: -3000, unit: '$', status: 'warn' as const },
  { label: 'Sharpe', value: 2.34, threshold: 1.5, unit: '', status: 'good' as const },
  { label: 'Max DD', value: -8.5, threshold: -15.0, unit: '%', status: 'safe' as const },
]

const navCurve = Array.from({ length: 40 }, (_, i) => ({
  t: i, nav: 200000 + i * 1000 + Math.sin(i * 0.3) * 5000 + Math.random() * 2000, benchmark: 200000 + i * 600,
}))

const sectorExposure = [
  { sector: '科技', value: 42, color: '#818cf8', lightColor: '#4f46e5' },
  { sector: '金融', value: 18, color: '#34d399', lightColor: '#059669' },
  { sector: '医疗', value: 12, color: '#f59e0b', lightColor: '#d97706' },
  { sector: '能源', value: 10, color: '#f87171', lightColor: '#dc2626' },
  { sector: '消费', value: 9, color: '#60a5fa', lightColor: '#2563eb' },
]

const statusMeta = {
  safe: { label: '安全', cls: 'bg-emerald-500/15 dark:bg-emerald-400/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 dark:border-emerald-400/30 transition-colors duration-300' },
  warn: { label: '预警', cls: 'bg-amber-500/15 dark:bg-amber-400/15 text-amber-600 dark:text-amber-400 border-amber-500/30 dark:border-amber-400/30 transition-colors duration-300' },
  good: { label: '优秀', cls: 'bg-sky-500/15 dark:bg-sky-400/15 text-sky-600 dark:text-sky-400 border-sky-500/30 dark:border-sky-400/30 transition-colors duration-300' },
  crit: { label: '超限', cls: 'bg-red-500/15 dark:bg-red-400/15 text-red-600 dark:text-red-400 border-red-500/30 dark:border-red-400/30 transition-colors duration-300' },
}

function DoughnutChart({ isDark }: { isDark: boolean }) {
  const total = exposureData.reduce((s, d) => s + d.value, 0)
  const r = 38, cx = 48, cy = 48, stroke = 14
  const circ = 2 * Math.PI * r
  let offset = 0
  const slices = exposureData.map((d) => { const dash = (d.value / total) * circ; const s = { ...d, dash, offset }; offset += dash; return s })
  return (
    <div className="relative w-24 h-24 flex-shrink-0">
      <svg viewBox="0 0 96 96" className="w-full h-full -rotate-90">
        {slices.map((s, i) => (<circle key={i} cx={cx} cy={cy} r={r} fill="none" stroke={isDark ? s.color : s.lightColor} className="transition-colors duration-300" strokeWidth={stroke} strokeDasharray={`${s.dash - 1} ${circ - s.dash + 1}`} strokeDashoffset={-s.offset} />))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[9px] text-muted-foreground">净值</span>
        <span className="text-xs font-bold tabular-nums">$245.7K</span>
      </div>
    </div>
  )
}

export function RiskModule() {
  const [isMounted, setIsMounted] = useState(false)
  const { theme } = useTheme()

  useEffect(() => {
    setIsMounted(true)
  }, [])

  if (!isMounted) return null

  const isDark = theme === 'dark'

  return (
    <div className="space-y-2">
      {/* ── Row 1: KPI Strip (Core) ──────────────────────────────── */}
      <div className="grid grid-cols-4 gap-2">
        {portfolioKpi.map((kpi, i) => (
          <div key={i} className="glass-card rounded-lg px-3 py-2 transition-colors duration-300">
            <p className="text-[9px] text-muted-foreground mb-0.5">{kpi.label}</p>
            <p className={cn('text-base font-bold font-mono tabular-nums leading-tight transition-colors duration-300', kpi.dir > 0 ? 'text-emerald-600 dark:text-emerald-400' : kpi.dir < 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{kpi.value}</p>
            <p className={cn('text-[10px] font-mono tabular-nums transition-colors duration-300', kpi.dir > 0 ? 'text-emerald-600/80 dark:text-emerald-400/80' : kpi.dir < 0 ? 'text-red-600/80 dark:text-red-400/80' : 'text-muted-foreground')}>{kpi.pct}</p>
          </div>
        ))}
      </div>

      {/* ── Row 2: Doughnut + Radar + Factors ────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-[180px_1fr_1fr] gap-2">
        {/* Doughnut */}
        <div className="glass-card rounded-lg p-3 transition-colors duration-300">
          <div className="flex items-center gap-1.5 mb-2">
            <ShieldAlert className="h-3 w-3 text-muted-foreground" />
            <span className="text-[9px] font-semibold text-muted-foreground uppercase">敞口</span>
          </div>
          <div className="flex items-center gap-3">
            <DoughnutChart isDark={isDark} />
            <div className="space-y-1">
              {exposureData.map((d) => (
                <div key={d.name} className="flex items-center gap-1.5 text-[9px]">
                  <span className="h-1.5 w-1.5 rounded-full transition-colors duration-300" style={{ background: isDark ? d.color : d.lightColor }} />
                  <span className="text-muted-foreground">{d.name}</span>
                  <span className="font-mono font-bold">{d.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Radar */}
        <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
          <div className="px-3 py-1.5 border-b border-border/30 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase">风险雷达</span>
            <button className="text-[9px] text-amber-600 dark:text-amber-400 transition-colors duration-300 flex items-center gap-1" title="预警设置"><Bell className="h-2.5 w-2.5" />设置</button>
          </div>
          <div className="p-1 h-40">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={riskRadar}>
                <PolarGrid stroke={isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.07)"} />
                <PolarAngleAxis dataKey="axis" tick={{ fill: isDark ? 'rgba(156,163,175,0.8)' : 'rgba(100,116,139,0.8)', fontSize: 9 }} />
                <Radar dataKey="current" stroke={isDark ? "#34d399" : "#059669"} fill={isDark ? "#34d399" : "#059669"} fillOpacity={0.15} strokeWidth={1.5} isAnimationActive={true} animationDuration={1200} animationEasing="ease-out" />
                <Radar dataKey="limit" stroke={isDark ? "rgba(239,68,68,0.5)" : "rgba(220,38,38,0.5)"} fill={isDark ? "rgba(239,68,68,0.05)" : "rgba(220,38,38,0.05)"} strokeWidth={1} strokeDasharray="3 2" isAnimationActive={true} animationDuration={1200} animationEasing="ease-out" />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Factors */}
        <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
          <div className="px-3 py-1.5 border-b border-border/30">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase">因子监控</span>
          </div>
          <div className="divide-y divide-border/15">
            {riskFactors.map((f, i) => {
              const meta = statusMeta[f.status]
              return (
                <div key={i} className="px-3 py-2 flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[10px] font-semibold">{f.label}</span>
                      <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded border', meta.cls)}>{meta.label}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[9px] text-muted-foreground">
                      <span className="font-mono font-bold text-foreground tabular-nums">
                        {f.unit === '$' ? `$${Math.abs(f.value).toLocaleString()}` : `${f.value}${f.unit}`}
                      </span>
                      <span className="opacity-50">/</span>
                      <span className="font-mono tabular-nums">限 {f.unit === '$' ? `$${Math.abs(f.threshold).toLocaleString()}` : `${f.threshold}${f.unit}`}</span>
                    </div>
                  </div>
                  {f.status === 'warn' && <AlertTriangle className="h-3 w-3 text-amber-600 dark:text-amber-400 animate-pulse transition-colors duration-300" />}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Row 3: NAV Curve + Sector ────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px] gap-2">
        {/* NAV Curve */}
        <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
          <div className="px-3 py-1.5 border-b border-border/30 flex items-center justify-between">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />净值曲线 · Alpha归因
            </span>
            <div className="flex gap-2 text-[9px]">
              {[{ k: '总收益', v: '+$3,421', c: 'text-emerald-600 dark:text-emerald-400' }, { k: 'Beta', v: '+$1,856', c: 'text-sky-600 dark:text-sky-400' }, { k: 'Alpha', v: '+$1,565', c: 'text-emerald-600 dark:text-emerald-400' }].map(({ k, v, c }) => (
                <span key={k}>{k}: <span className={cn('font-mono font-bold transition-colors duration-300', c)}>{v}</span></span>
              ))}
            </div>
          </div>
          <div className="p-2 h-32">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={navCurve}>
                <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)"} />
                <XAxis dataKey="t" hide />
                <YAxis domain={['auto', 'auto']} hide />
                <Tooltip contentStyle={{ background: isDark ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)', borderRadius: '6px', fontSize: 10, color: isDark ? '#f8fafc' : '#0f172a' }} formatter={(v: any) => [`$${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`, '']} />
                <Line type="monotone" dataKey="nav" stroke={isDark ? "#34d399" : "#059669"} strokeWidth={1.5} dot={false} />
                <Line type="monotone" dataKey="benchmark" stroke={isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)"} strokeWidth={1} dot={false} strokeDasharray="4 2" />
                <ReferenceLine y={200000} stroke={isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)"} strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sector */}
        <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
          <div className="px-3 py-1.5 border-b border-border/30">
            <span className="text-[9px] font-semibold text-muted-foreground uppercase">板块暴露</span>
          </div>
          <div className="p-2 h-32">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sectorExposure} layout="vertical" margin={{ left: 0, right: 8 }}>
                <XAxis type="number" hide domain={[0, 50]} />
                <YAxis type="category" dataKey="sector" width={28} tick={{ fill: isDark ? 'rgba(156,163,175,0.8)' : 'rgba(100,116,139,0.8)', fontSize: 9 }} />
                <Tooltip contentStyle={{ background: isDark ? 'oklch(0.18 0.01 270)' : 'rgba(255, 255, 255, 0.95)', border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)', borderRadius: '6px', fontSize: 10, color: isDark ? '#f8fafc' : '#0f172a' }} formatter={(v: any) => [`${v}%`, '']} cursor={{ fill: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }} />
                <Bar dataKey="value" radius={[0, 2, 2, 0]}>
                  {sectorExposure.map((d, i) => (<Cell key={i} fill={isDark ? d.color : d.lightColor} className="transition-colors duration-300" fillOpacity={0.75} />))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
