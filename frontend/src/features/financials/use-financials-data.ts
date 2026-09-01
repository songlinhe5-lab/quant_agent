/**
 * FIN-07 · 财报看板数据 hook：loading / error / data 三态 + 请求竞态防护。
 * 低频分析数据直接进 React 状态（零 GC 铁律只约束 Tick，AGENTS §3）。
 */

import { useEffect, useState } from 'react'

import { apiClient } from '@/lib/api-client'
import logger from '@/lib/logger'

export interface FinancialsDataState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** params 序列化作为依赖键，避免调用方每次渲染传新对象导致死循环 */
export function useFinancialsData<T>(path: string, params?: Record<string, unknown>) {
  const key = params ? JSON.stringify(params) : ''
  const [state, setState] = useState<FinancialsDataState<T>>({ data: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    apiClient
      .get<{ data: T }>(path, params)
      .then((res) => {
        if (!cancelled) setState({ data: res.data ?? null, loading: false, error: null })
      })
      .catch((e) => {
        if (!cancelled) {
          logger.warn('财报数据加载失败', { path, error: String(e?.message || e) })
          setState({ data: null, loading: false, error: String(e?.message || e) })
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key])

  return state
}
