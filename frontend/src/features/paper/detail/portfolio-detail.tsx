/**
 * PT-02b: 组合详情页容器
 */
'use client'

import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { NavChart } from './nav-chart'
import { CompareChart } from './compare-chart'
import { DriftPanel } from './drift-panel'
import { FillsTable } from './fills-table'

interface PortfolioDetail {
  id: string
  name: string
  strategy_name: string
  market: string
  status: string
  initial_capital: number
  positions: Array<{
    symbol: string
    qty: number
    avg_cost: number
  }>
}

type TabKey = 'overview' | 'compare' | 'fills'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'compare', label: '对比' },
  { key: 'fills', label: '流水' },
]

export function PortfolioDetail() {
  const { portfolioId } = useParams<{ portfolioId: string }>()
  const navigate = useNavigate()
  const [portfolio, setPortfolio] = useState<PortfolioDetail | null>(null)
  const [tab, setTab] = useState<TabKey>('overview')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!portfolioId) return
    setLoading(true)
    apiClient
      .get<any>(`/paper/portfolios/${portfolioId}`)
      .then((res) => setPortfolio(res.data?.data || null))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [portfolioId])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!portfolio) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p>组合不存在或已删除</p>
        <button onClick={() => navigate('/paper')} className="mt-2 text-sm text-primary hover:underline">
          返回列表
        </button>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/paper')}
          className="p-1.5 rounded-md hover:bg-accent transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div>
          <h1 className="text-xl font-bold">{portfolio.name}</h1>
          <p className="text-xs text-muted-foreground">
            {portfolio.strategy_name} · {portfolio.market} · {portfolio.status}
          </p>
        </div>
      </div>

      {/* Position Summary Cards */}
      {portfolio.positions.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {portfolio.positions.slice(0, 4).map((pos) => (
            <div key={pos.symbol} className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-foreground truncate">{pos.symbol}</p>
              <p className="text-lg font-bold font-mono">{pos.qty}</p>
              <p className="text-xs text-muted-foreground">成本 {pos.avg_cost.toFixed(2)}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
              tab === t.key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'overview' && <NavChart portfolioId={portfolio.id} />}
      {tab === 'compare' && <CompareChart portfolioId={portfolio.id} />}
      {tab === 'fills' && <FillsTable portfolioId={portfolio.id} />}

      {/* Drift Panel (always visible on overview) */}
      {tab === 'overview' && <DriftPanel portfolioId={portfolio.id} />}
    </div>
  )
}
