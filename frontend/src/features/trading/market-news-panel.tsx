'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { NewsStream } from '@/features/data-center/news-stream'

/**
 * PROD-05 深化：默认行情工作区的「新闻流」次面板。
 * 自包含获取 /macro/news，复用 data-center 的 NewsStream 渲染。
 * 由外层 .resp-auto-panels + [data-secondary-panel] 控制在 ≥1920px 自动展开。
 */
export function MarketNewsPanel() {
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
    <div className="h-full p-2">
      <NewsStream
        news={news}
        visibleNewsCount={visibleNewsCount}
        setVisibleNewsCount={setVisibleNewsCount}
        className="h-full"
      />
    </div>
  )
}
