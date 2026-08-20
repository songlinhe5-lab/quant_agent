/**
 * 因子归因面板 — 兑现导航"高级归因"承诺
 * 接入孤儿端点 GET /risk/attribution (Jensen's Alpha 单因子: α/β/R²/收益分解)
 */
import { useState, useEffect } from 'react'
import { Loader2, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'

interface AttributionResult {
  alpha?: number
  beta?: number
  r_squared?: number
  beta_contrib?: number
  total_return?: number
  attribution?: { alpha_pct: number; beta_pct: number; residual_pct: number }
}

export function RiskAttributionPanel({ market }: { market: string }) {
  const [data, setData] = useState<AttributionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient.get<AttributionResult>(`/risk/attribution?market=${market}`)
      .then((res: any) => {
        if (cancelled) return
        const d = res.data?.data || res.data
        setData(d)
      })
      .catch(() => { if (!cancelled) setError('归因数据获取失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [market])

  const attr = data?.attribution
  const hasData = data && (data.alpha !== undefined || data.beta !== undefined)

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-3 py-1 border-b border-border/20 flex items-center justify-between">
        <span className="text-[9px] font-semibold text-muted-foreground uppercase flex items-center gap-1">
          Jensen Alpha 归因
          <span className="text-[7px] px-1 py-px rounded bg-violet-500/10 text-violet-500 font-mono">/risk/attribution</span>
        </span>
        <span className="text-[8px] text-muted-foreground font-mono">单因子 Market 口径</span>
      </div>

      {loading && (
        <div className="py-6 flex flex-col items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-[9px]">归因计算中...</span>
        </div>
      )}
      {error && (
        <div className="py-4 text-center text-[9px] text-amber-500">{error}</div>
      )}
      {!loading && !error && (!hasData || (data?.alpha === 0 && data?.beta === 0)) && (
        <div className="py-4 text-center text-[9px] text-muted-foreground">持仓或 K 线不足，暂无归因数据</div>
      )}
      {!loading && !error && hasData && (
        <div className="p-2 space-y-2">
          {/* α / β / R² 三卡 */}
          <div className="grid grid-cols-3 gap-1.5">
            <div className="bg-muted/20 rounded-lg py-2 text-center">
              <p className="text-[8px] text-muted-foreground">Alpha α (年化)</p>
              <p className={cn('text-sm font-bold font-mono tabular-nums mt-0.5', (data?.alpha || 0) >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                {(data?.alpha || 0) >= 0 ? '+' : ''}{(data?.alpha || 0).toFixed(1)}%
              </p>
            </div>
            <div className="bg-muted/20 rounded-lg py-2 text-center">
              <p className="text-[8px] text-muted-foreground">Beta β</p>
              <p className="text-sm font-bold font-mono tabular-nums mt-0.5 text-foreground">{(data?.beta || 0).toFixed(2)}</p>
            </div>
            <div className="bg-muted/20 rounded-lg py-2 text-center">
              <p className="text-[8px] text-muted-foreground">拟合度 R²</p>
              <p className="text-sm font-bold font-mono tabular-nums mt-0.5 text-foreground">{(data?.r_squared || 0).toFixed(2)}</p>
            </div>
          </div>

          {/* 收益贡献分解条 */}
          <div>
            <p className="text-[8px] text-muted-foreground mb-1">区间收益分解 (相对基准)</p>
            {attr && (attr.beta_pct || attr.alpha_pct || attr.residual_pct) ? (
              <div className="flex h-4 rounded overflow-hidden text-[8px] font-bold text-white">
                <span className="flex items-center justify-center bg-blue-500" style={{ width: `${Math.max(attr.beta_pct, 0)}%` }}>β {attr.beta_pct}%</span>
                <span className="flex items-center justify-center bg-emerald-600" style={{ width: `${Math.max(attr.alpha_pct, 0)}%` }}>α {attr.alpha_pct}%</span>
                <span className="flex items-center justify-center bg-gray-500" style={{ width: `${Math.max(attr.residual_pct, 0)}%` }}>残差 {attr.residual_pct}%</span>
              </div>
            ) : (
              <div className="text-[8px] text-muted-foreground">无分解数据</div>
            )}
            <p className="text-[7px] text-muted-foreground mt-1">
              总收益 {(data?.total_return || 0).toFixed(1)}% = β 贡献 + α + 残差 · 单因子 (Market) 口径, 非 Brinson
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
