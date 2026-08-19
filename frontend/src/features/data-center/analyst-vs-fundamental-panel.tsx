import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface AnalystVsFundamentalData {
  ticker?: string
  target_price?: number
  current_price?: number
  upside_pct?: number
  verdict?: string
  consensus_is_third_party_expectation?: boolean
  source?: string
  note?: string
}

function verdictTone(v?: string): string {
  if (v === 'sell_side_bullish') return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
  if (v === 'sell_side_bearish') return 'text-red-400 border-red-500/30 bg-red-500/10'
  return 'text-amber-400 border-amber-500/30 bg-amber-500/10'
}

export function AnalystVsFundamentalPanel({ ticker = 'US.AAPL' }: { ticker?: string }) {
  const [data, setData] = useState<AnalystVsFundamentalData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: AnalystVsFundamentalData }>(`/market/analyst-vs-fundamental/${ticker}`)
      .then((res) => {
        // 方案 B：路由返回扁平 payload，业务字段在 panel 子键（res.data.panel）
        if (!cancelled) setData((res.data as any)?.panel ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载卖方共识 vs 基本面 ({ticker})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        共识对比数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无卖方共识对比数据</div>

  const upside = data.upside_pct
  const upsideTone = upside == null ? 'text-slate-300' : upside >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">卖方共识 vs 基本面</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker}</span>
        {data.consensus_is_third_party_expectation && (
          <span className="ml-auto text-[8px] font-mono text-amber-400/80 border border-amber-500/20 px-1.5 py-0.5 rounded">卖方预期 · 非实际</span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">当前价</div>
          <div className="text-base font-semibold font-mono text-foreground/90">{data.current_price != null ? data.current_price.toFixed(2) : '--'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">目标价(共识均值)</div>
          <div className="text-base font-semibold font-mono text-[#8b5cf6]">{data.target_price != null ? data.target_price.toFixed(2) : '--'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">隐含上行空间</div>
          <div className={'text-base font-semibold font-mono ' + upsideTone}>{upside != null ? (upside >= 0 ? '+' : '') + (upside * 100).toFixed(1) + '%' : '--'}</div>
        </div>
      </div>
      {data.verdict && (
        <div className="px-3 pb-3">
          <span className={'text-[11px] font-mono px-2 py-0.5 rounded border ' + verdictTone(data.verdict)}>
            {data.verdict === 'sell_side_bullish' ? '卖方看多（目标价高于现价>15%）' : data.verdict === 'sell_side_bearish' ? '卖方看空（目标价低于现价>5%）' : '中性/预期收敛'}
          </span>
        </div>
      )}
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 分析师共识 + 基本面合并'} · {data.note || '共识为第三方卖方预期，非实际成交价'}
      </div>
    </div>
  )
}
