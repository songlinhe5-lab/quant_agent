'use client'

/**
 * BRD-01: 盘前早报生成 Modal
 * Dashboard 顶部「☕ 生成早报」按钮触发。打开即调 POST /briefing/generate，
 * 用 BriefingMarkdown 渲染返回的 Markdown，支持「复制」与「分享链接」。
 */
import { useCallback, useEffect, useState } from 'react'
import { Coffee, Copy, Share2, Loader2, RefreshCw, Globe2, ShieldAlert } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { BriefingMarkdown } from './briefing-markdown'

// 与后端 MARKET_TICKERS 对齐：BRD-01 支持的市场范围
const MARKETS = ['全球', '美股', '港股', 'A股'] as const

export interface BriefingData {
  id: string
  date: string
  market: string
  markdown: string
  source_tools: string[]
  created_at: string
}

export function MorningBriefingModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [loading, setLoading] = useState(false)
  const [market, setMarket] = useState<string>('全球')
  const [briefing, setBriefing] = useState<BriefingData | null>(null)
  const [healthRisk, setHealthRisk] = useState<
    Array<{ ticker: string; overfit_risk?: boolean; alpha_decay?: boolean; summary?: string }>
  >([])
  const [error, setError] = useState<string | null>(null)
  const { toast } = useToast()

  const generate = useCallback(
    async (mkt: string) => {
      setLoading(true)
      setError(null)
      try {
      const res = await apiClient.post<{ data: BriefingData }>(
        `/briefing/generate?market=${encodeURIComponent(mkt)}`,
      )
      setBriefing(res.data)
      // 回测健康度风险项高亮卡数据：拉取已落库的健康度，筛出风险条目
      try {
        const health = await apiClient.get<{
          data: Array<{ ticker: string; overfit_risk?: boolean; alpha_decay?: boolean; summary?: string }>
        }>('/backtest/health')
        const list = health?.data?.data ?? []
        setHealthRisk(list.filter((e) => e.overfit_risk || e.alpha_decay))
      } catch {
        setHealthRisk([])
      }
      } catch (e: any) {
        const msg = e?.message || '早报生成失败'
        setError(msg)
        toast({ title: '早报生成失败', description: msg, variant: 'destructive' })
      } finally {
        setLoading(false)
      }
    },
    [toast],
  )

  // 每次打开都重新生成一份新鲜早报
  useEffect(() => {
    if (open) {
      setBriefing(null)
      void generate(market)
    }
  }, [open, market, generate])

  const onMarketChange = (mkt: string) => {
    setMarket(mkt)
    if (open) void generate(mkt)
  }

  const copy = async (text: string, msg: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast({ title: msg })
    } catch {
      toast({ title: '复制失败', variant: 'destructive' })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden !flex !flex-col gap-3">
        <DialogHeader>
          <div className="flex items-start justify-between gap-3">
            <DialogTitle className="flex items-center gap-2">
              <Coffee className="w-5 h-5 text-amber-500" />
              🌤️ Quant Agent 盘前早报
            </DialogTitle>
            <Select value={market} onValueChange={onMarketChange}>
              <SelectTrigger size="sm" className="w-28 gap-1.5">
                <Globe2 className="w-3.5 h-3.5 text-muted-foreground" />
                <SelectValue placeholder="市场" />
              </SelectTrigger>
              <SelectContent>
                {MARKETS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogDescription>宏观日历 · 核心标的 · 舆情提纯 · 多空概率矩阵</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto pr-2 min-h-0">
          {loading && (
            <div className="flex items-center gap-2 text-muted-foreground py-8">
              <Loader2 className="w-4 h-4 animate-spin" />
              主脑正在推演盘前格局…
            </div>
          )}
          {error && <div className="text-red-500 text-sm py-4">{error}</div>}
          {healthRisk.length > 0 && (
            <div className="mb-3 rounded-xl border border-red-500/40 bg-red-500/10 p-3">
              <div className="flex items-center gap-2 text-red-300">
                <ShieldAlert className="h-4 w-4" />
                <span className="text-sm font-semibold">⚠️ 回测健康度风险项</span>
              </div>
              <ul className="mt-2 space-y-1">
                {healthRisk.map((e) => (
                  <li key={e.ticker} className="text-xs text-red-200/90">
                    <span className="font-mono">{e.ticker}</span>
                    {e.summary ? `：${e.summary.slice(0, 80)}` : '：过拟合 / Alpha 衰减风险'}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {briefing && <BriefingMarkdown content={briefing.markdown} />}
        </div>

        <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40">
          <button
            onClick={() => void generate(market)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border/60 hover:bg-secondary/60 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={loading ? 'w-3.5 h-3.5 animate-spin' : 'w-3.5 h-3.5'} />
            重新生成
          </button>
          <div className="flex gap-2">
            <button
              onClick={() => briefing && copy(briefing.markdown, '已复制早报 Markdown')}
              disabled={!briefing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              <Copy className="w-3.5 h-3.5" />
              复制
            </button>
            <button
              onClick={() =>
                briefing &&
                copy(`${window.location.origin}/briefing/${briefing.id}`, '分享链接已复制')
              }
              disabled={!briefing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border/60 hover:bg-secondary/60 transition-colors disabled:opacity-50"
            >
              <Share2 className="w-3.5 h-3.5" />
              分享链接
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
