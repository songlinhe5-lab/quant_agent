/**
 * PT-02b: 组合详情页容器
 */
'use client'

import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, RefreshCw, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'
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

      {/* AI-07 实盘教练卡（ai07 开关控制，挂载于 overview） */}
      {tab === 'overview' && <AiCoachCard portfolioId={portfolio.id} />}
    </div>
  )
}

/**
 * AI-07 实盘教练卡：拉 /paper/portfolios/{id}/readiness → 展示体检结论 + 能否实盘 + 关键指标。
 * ai07 开关控制；无数据 / LLM 未配置时诚实降级，不编造。
 */
function AiCoachCard({ portfolioId }: { portfolioId: string }) {
  const ai07Enabled = useAiPushPrefStore((s) => s.isEnabled('ai07'))
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<{
    ready_for_live: boolean | null
    metrics: Record<string, any>
    coach_advice: string | null
    confidence: number | null
    message: string | null
  } | null>(null)

  useEffect(() => {
    if (!ai07Enabled) return
    let alive = true
    setLoading(true)
    setData(null)
    ;(async () => {
      try {
        const res = await apiClient.get(`/paper/portfolios/${portfolioId}/readiness`)
        const body = res.data || res
        if (alive && body) setData(body)
      } catch (e: any) {
        if (alive) setData({ ready_for_live: null, metrics: {}, coach_advice: null, confidence: null, message: e?.response?.data?.message || '教练服务调用失败' })
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [ai07Enabled, portfolioId])

  if (!ai07Enabled) return null

  if (loading) {
    return (
      <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span className="text-[11px] font-semibold text-primary">AI 实盘教练</span>
          <span className="text-[9px] text-muted-foreground">体检中…</span>
        </div>
      </div>
    )
  }

  if (!data) return null

  const m = data.metrics || {}
  const ready = data.ready_for_live
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <Sparkles className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] font-semibold text-primary">AI 实盘教练</span>
        {ready === true && <span className="text-[10px] text-green-400">✓ 可转实盘</span>}
        {ready === false && <span className="text-[10px] text-red-400">✗ 暂不宜实盘</span>}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] mb-1.5">
        <div>
          <span className="text-muted-foreground">最大回撤 </span>
          <span className="font-mono">{m.max_drawdown != null ? `${(m.max_drawdown * 100).toFixed(1)}%` : '—'}</span>
        </div>
        <div>
          <span className="text-muted-foreground">连续亏损 </span>
          <span className="font-mono">{m.consecutive_losses ?? '—'} 天</span>
        </div>
        <div>
          <span className="text-muted-foreground">偏离基准 </span>
          <span className="font-mono">{m.cumulative_drift != null ? `${(m.cumulative_drift * 100).toFixed(1)}%` : '—'}</span>
        </div>
        <div>
          <span className="text-muted-foreground">跟踪误差 </span>
          <span className="font-mono">{m.tracking_error != null ? m.tracking_error.toFixed(4) : '—'}</span>
        </div>
      </div>
      {data.coach_advice && <p className="text-[10px] text-foreground/90 leading-relaxed">{data.coach_advice}</p>}
      {data.message && <p className="text-[9px] text-muted-foreground/70 mt-1">{data.message}</p>}
      <p className="pt-1 mt-1 text-[9px] text-muted-foreground/50 border-t border-border/30">
        AI 生成 · 仅供参考，不构成实盘建议
      </p>
    </div>
  )
}
