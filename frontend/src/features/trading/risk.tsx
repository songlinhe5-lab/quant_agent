'use client'

import { useState, useEffect, useMemo } from 'react'
import { Loader2, RefreshCw, ShieldAlert, Clock } from 'lucide-react'
import { useTheme } from 'next-themes'
import { apiClient } from '@/lib/api-client'
import { AccountSection } from './risk-account-section'
import type { AccountsMap } from './risk-types'
import { MARKET_LABELS } from './risk-types'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'
import { useBackendStatusStore } from '@/stores/useBackendStatusStore'
import { cn } from '@/lib/utils'

// ── 账户切换条 (A区) ──────────────────────────────────────────────────────────

function AccountSwitcher({ accounts, active, onSelect, ts }: {
  accounts: AccountsMap
  active: string
  onSelect: (m: string) => void
  ts: number | null
}) {
  const markets = useMemo(() => Object.keys(accounts), [accounts])

  return (
    <div className="flex items-stretch gap-2 flex-wrap">
      {markets.length > 0 ? markets.map(m => {
        const acc = accounts[m]
        const meta = MARKET_LABELS[m] || { name: m, flag: '🌐' }
        const plDir = (acc?.kpi?.today_pl || 0) >= 0 ? 1 : -1
        return (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className={cn(
              'flex flex-col gap-0.5 px-3.5 py-2 rounded-xl border text-left transition-all min-w-[210px]',
              active === m
                ? 'border-blue-500/60 bg-[#1E2A44] shadow-sm'
                : 'border-border/40 bg-card hover:border-blue-500/30 hover:bg-card/80'
            )}
          >
            <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              {meta.flag} {meta.name}
              <span className="text-[8px] font-mono text-amber-500/90 bg-amber-500/10 px-1 py-px rounded">Futu SIMULATE</span>
            </span>
            <span className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono tabular-nums">
              <b className="text-[12px] text-foreground">{acc?.kpi?.nav_fmt || '--'}</b>
              <span className={plDir >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {acc?.kpi?.today_pl >= 0 ? '+' : ''}{(acc?.kpi?.today_pl_pct || 0).toFixed(2)}%
              </span>
              <span>{acc?.position_count || 0} 只持仓</span>
            </span>
          </button>
        )
      }) : (
        <div className="text-[10px] text-muted-foreground">暂无账户</div>
      )}
      <div className="ml-auto flex items-center gap-2 text-[10px] text-muted-foreground self-center">
        <Clock className="h-3 w-3" />
        {ts ? <>数据时点 {new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 新鲜</> : '等待时点'}
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
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null)
  const [ts, setTs] = useState<number | null>(null)
  const [activeMarket, setActiveMarket] = useState<string>('HK')
  const backendStatus = useBackendStatusStore(s => s.status)

  useEffect(() => { setIsMounted(true); fetchRiskData() }, [])

  async function fetchRiskData() {
    try {
      setLoading(true)
      const res = await apiClient.get('/risk/dashboard')
      const d = res.data?.data || res.data
      if (d?.accounts) {
        setAccounts(d.accounts)
        setTs(d.ts ?? null)
        // 默认选中第一个存在的账户
        const keys = Object.keys(d.accounts)
        if (keys.length > 0 && !keys.includes(activeMarket)) setActiveMarket(keys[0])
      }
      setEmptyMessage(d?.status === 'empty' || !d?.accounts ? (d?.message || '暂无账户数据') : null)
    } catch (err) {
      console.error('[Risk] 获取风控数据失败:', err)
      setEmptyMessage('风控数据获取失败：数据源暂不可用')
    } finally {
      setLoading(false)
    }
  }

  // PROD-01: 将组合上下文写入 AI 副驾，实现"场景感知助手"
  useEffect(() => {
    const markets = Object.keys(accounts)
    if (markets.length === 0) {
      useCopilotContextStore.getState().clearContext()
      return
    }
    const lines = markets.map((m) => {
      const acc = accounts[m]
      const name = MARKET_LABELS[m]?.name ?? m
      return `${m} · ${name}: 净值 ${acc.kpi.nav} ${acc.kpi.currency} · 持仓 ${acc.position_count} 笔`
    })
    useCopilotContextStore.getState().setContext({
      kind: 'risk',
      title: '风控',
      summary: lines.join('\n'),
    })
  }, [accounts])

  if (!isMounted) return null
  const isDark = theme === 'dark'
  // STRAT: 账户切换本地化 — 一次全量返回, 前端仅重渲染选中账户
  const activeAccount = accounts[activeMarket]
  const isOffline = backendStatus === 'offline'

  return (
    <div className="space-y-3">
      {/* SANDBOX 横幅 + 断连联动 (E区) */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-amber-500/8 border border-amber-500/25 text-[10px] text-amber-600 dark:text-amber-400">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
        <b>SANDBOX</b>
        <span className="text-muted-foreground">模拟盘账户 · 单次推演无持久账本 · 数据源 Futu 模拟盘 (FUTU_TRD_ENV=SIMULATE)</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono">GET /risk/dashboard · 一次全量</span>
          <button onClick={fetchRiskData} disabled={loading} className="px-2 py-0.5 rounded border border-border/40 hover:bg-secondary/40 transition-colors flex items-center gap-1">
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} /> 刷新
          </button>
        </div>
      </div>

      {/* A 账户切换条 */}
      <AccountSwitcher accounts={accounts} active={activeMarket} onSelect={setActiveMarket} ts={ts} />

      {/* 数据区 (STALE 遮罩联动) */}
      <div className={cn('relative transition-opacity duration-300', isOffline && 'opacity-60 saturate-50')}>
        {isOffline && (
          <div className="absolute -top-2 left-2 z-10 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/40">
            <ShieldAlert className="h-3 w-3 text-amber-500" />
            <span className="text-[10px] font-semibold text-amber-500">STALE</span>
          </div>
        )}

        {activeAccount ? (
          <AccountSection key={activeMarket} market={activeMarket} account={activeAccount} isDark={isDark} loading={loading} />
        ) : (
          <div className="flex flex-col items-center justify-center h-32 gap-1 text-center px-4">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              <>
                <span className="text-[10px] text-amber-500/90">{emptyMessage || '暂无账户数据'}</span>
                <span className="text-[9px] text-muted-foreground/60">数据源恢复后将自动重试</span>
              </>
            )}
            {loading ? <span className="text-[10px] text-muted-foreground">加载风控数据...</span> : null}
          </div>
        )}

        {isOffline && activeAccount && (
          <div className="absolute inset-0 z-20 flex items-start justify-center pt-10 pointer-events-none">
            <span className="px-3 py-1.5 rounded-lg bg-background/90 border border-amber-500/40 text-[10px] text-amber-500 shadow-sm">
              数据为最后一次成功快照，可能滞后 · /health 探测恢复即自动摘除
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
