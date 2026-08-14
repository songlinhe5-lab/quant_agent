'use client'

/**
 * BRD-01: 早报分享落地页 (/briefing/:id)
 * 通过 Modal 内的「分享链接」复制的 URL 打开，按分享短码拉取已生成的早报并渲染。
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { BriefingMarkdown } from './briefing-markdown'
import type { BriefingData } from './morning-briefing-modal'

export function BriefingSharePage() {
  const { id } = useParams<{ id: string }>()
  const [briefing, setBriefing] = useState<BriefingData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    setLoading(true)
    setError(null)
    apiClient
      .get<{ status: string; data: BriefingData }>(`/briefing/share/${id}`)
      .then((res) => {
        // 后端返回 {status, data}，经全局信封中间件再包一层，apiClient 解包后
        // res.data = {status, data}，真实 BriefingData 在 .data
        if (mounted) setBriefing(res.data?.data ?? res.data)
      })
      .catch((e: any) => {
        if (mounted) setError(e?.message || '加载失败')
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [id])

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="mb-4">
        <h1 className="text-lg font-bold">🌤️ Quant Agent 盘前早报</h1>
        <p className="text-xs text-muted-foreground">
          分享链接 · {briefing?.market} · {briefing?.date || id}
        </p>
      </div>
      {loading && (
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}
      {error && <div className="text-red-500 text-sm">{error}</div>}
      {briefing && <BriefingMarkdown content={briefing.markdown} />}
    </div>
  )
}
