'use client'

import { useEffect, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { NewsStream } from '@/features/data-center/news-stream'

/**
 * PROD-05 深化：默认行情工作区的「新闻流」次面板。
 * 自包含获取 /macro/news，复用 data-center 的 NewsStream 渲染。
 * 由外层 .resp-auto-panels + [data-secondary-panel] 控制在 ≥1920px 自动展开。
 * 提供 onClose 让用户在盯盘聚焦时收起该面板。
 */
export function MarketNewsPanel({ onClose }: { onClose?: () => void }) {
  const [news, setNews] = useState<any[]>([])
  const [visibleNewsCount, setVisibleNewsCount] = useState(8)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const res = await apiClient.get('/macro/news?limit=50')
        if (!mounted) return
        if (res.data?.status === 'success') {
          setNews(res.data.data || [])
        } else {
          setError(true)
        }
      } catch {
        if (mounted) setError(true)
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-[11px] text-muted-foreground/70 px-4 text-center">
        新闻流暂不可用
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {onClose && (
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-border/40 shrink-0">
          <span className="text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide">新闻流</span>
          <button
            type="button"
            onClick={onClose}
            title="收起新闻流面板"
            className="rounded p-0.5 text-muted-foreground/60 transition-colors hover:bg-secondary/60 hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 p-2">
        <NewsStream
          news={news}
          visibleNewsCount={visibleNewsCount}
          setVisibleNewsCount={setVisibleNewsCount}
          className="h-full"
        />
      </div>
    </div>
  )
}
