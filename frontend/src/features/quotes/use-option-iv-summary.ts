import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

export interface OptionIvSummary {
  atmIv?: number
  ivPercentile?: number
  rv30d?: number
  skew?: number
}

/**
 * 期权 IV 指标条数据源（设计稿：ATM IV / IV 分位 / 30日已实现 / Skew）。
 * 优先请求聚合接口 /market/option-iv-summary；若后端暂无该端点则保持为 undefined（UI 显示 --）。
 */
export function useOptionIvSummary(ticker: string) {
  const [data, setData] = useState<OptionIvSummary | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!ticker) {
      setData(null)
      return
    }
    apiClient
      .get<{ data: OptionIvSummary }>(
        `/market/option-iv-summary?ticker=${encodeURIComponent(ticker)}`,
      )
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  return data
}
