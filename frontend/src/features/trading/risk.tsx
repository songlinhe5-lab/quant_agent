'use client'

import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { useTheme } from 'next-themes'
import { apiClient } from '@/lib/api-client'
import { AccountSection } from './risk-account-section'
import type { AccountsMap } from './risk-types'
import { MARKET_LABELS } from './risk-types'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'

// ── Main Component ───────────────────────────────────────────────────────────

export function RiskModule() {
  const [isMounted, setIsMounted] = useState(false)
  const [loading, setLoading] = useState(true)
  const { theme } = useTheme()
  const [accounts, setAccounts] = useState<AccountsMap>({})
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null)

  useEffect(() => { setIsMounted(true); fetchRiskData() }, [])

  async function fetchRiskData() {
    try {
      setLoading(true)
      const res = await apiClient.get('/risk/dashboard')
      const d = res.data?.data || res.data
      if (d?.accounts) setAccounts(d.accounts)
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
    const markets = ['HK', 'US'].filter((m) => accounts[m])
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
  const activeMarkets = ['HK', 'US'].filter(m => accounts[m])

  return (
    <div className="space-y-3">
      {activeMarkets.length > 0 ? (
        activeMarkets.map(market => (
          <AccountSection key={market} market={market} account={accounts[market]} isDark={isDark} loading={loading} />
        ))
      ) : (
        <div className="flex flex-col items-center justify-center h-32 gap-1 text-center px-4">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : (
            <>
              <span className="text-[10px] text-amber-500/90">
                {emptyMessage || '暂无账户数据'}
              </span>
              <span className="text-[9px] text-muted-foreground/60">
                数据源恢复后将自动重试
              </span>
            </>
          )}
          {loading ? <span className="text-[10px] text-muted-foreground">加载风控数据...</span> : null}
        </div>
      )}
    </div>
  )
}
