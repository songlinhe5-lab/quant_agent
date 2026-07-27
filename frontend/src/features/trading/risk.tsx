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
        <div className="flex items-center justify-center h-32 text-[10px] text-muted-foreground">
          {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
          {loading ? '加载风控数据...' : '暂无账户数据'}
        </div>
      )}
    </div>
  )
}
