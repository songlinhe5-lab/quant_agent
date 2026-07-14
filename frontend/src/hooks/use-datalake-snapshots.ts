/**
 * 数据湖快照 API（DQ-03e · FE-PROD-04）
 */
import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import logger from '@/lib/logger'
import type { DataLakeSnapshot } from '@/types/datalake'

function unwrapList(res: { data?: unknown }): DataLakeSnapshot[] {
  const body = res?.data as { status?: string; data?: DataLakeSnapshot[] } | DataLakeSnapshot[] | undefined
  if (Array.isArray(body)) return body
  if (body && typeof body === 'object' && Array.isArray(body.data)) return body.data
  return []
}

function unwrapOne(res: { data?: unknown } | null): DataLakeSnapshot | null {
  if (!res) return null
  const body = res.data as { status?: string; data?: DataLakeSnapshot } | DataLakeSnapshot | undefined
  if (!body || typeof body !== 'object') return null
  if ('snapshot_id' in body && typeof (body as DataLakeSnapshot).snapshot_id === 'string') {
    return body as DataLakeSnapshot
  }
  if ('data' in body && body.data && typeof body.data === 'object') {
    return body.data as DataLakeSnapshot
  }
  return null
}

export function useDatalakeSnapshots(autoLoad = true) {
  const [snapshots, setSnapshots] = useState<DataLakeSnapshot[]>([])
  const [latest, setLatest] = useState<DataLakeSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchSnapshots = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const listRes = await apiClient.get('/datalake/snapshots', { status: 'published', limit: 50 })
      setSnapshots(unwrapList(listRes))

      try {
        const latestRes = await apiClient.get('/datalake/snapshots/latest')
        setLatest(unwrapOne(latestRes))
      } catch {
        setLatest(null)
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '加载快照失败'
      setError(msg)
      logger.error('[Datalake] 加载快照失败', e as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (autoLoad) void fetchSnapshots()
  }, [autoLoad, fetchSnapshots])

  return { snapshots, latest, loading, error, fetchSnapshots }
}
