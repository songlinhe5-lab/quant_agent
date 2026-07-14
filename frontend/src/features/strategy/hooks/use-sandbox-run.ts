/**
 * STRAT-05: Sandbox Run Hook
 * AbortController 竞态取消 + 300ms debounce + 请求序号过期丢弃
 */
import { useRef, useCallback } from 'react'
import { apiClient } from '@/lib/api-client'

interface SandboxRunParams {
  source_code: string
  class_name: string
  params: Record<string, any>
  ticker: string
  period: string
  initial_capital: number
  data_source: string
  debug_mode: boolean
  data_snapshot_id?: string
  random_seed?: number
}

interface UseSandboxRunOptions {
  onSuccess?: (data: any) => void
  onError?: (error: string) => void
  debounceMs?: number
}

export function useSandboxRun(options: UseSandboxRunOptions = {}) {
  const abortControllerRef = useRef<AbortController | null>(null)
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestSeqRef = useRef(0)

  const run = useCallback(
    async (params: SandboxRunParams) => {
      // Abort previous in-flight request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }

      // Create new AbortController
      const controller = new AbortController()
      abortControllerRef.current = controller

      // Increment request sequence
      const currentSeq = ++requestSeqRef.current

      try {
        const res = await apiClient.post('/strategy/run-sandbox', params, {
          signal: controller.signal,
        })

        // Check if this response is still relevant (not superseded)
        if (currentSeq !== requestSeqRef.current) {
          return // Discard stale response
        }

        if (res.data?.status === 'success') {
          options.onSuccess?.(res.data.data)
        } else {
          options.onError?.(res.data?.message || '沙箱运行失败')
        }

        return res.data
      } catch (e: any) {
        // Ignore abort errors
        if (e.name === 'CanceledError' || e.message === 'canceled') {
          return
        }

        // Check if this response is still relevant
        if (currentSeq !== requestSeqRef.current) {
          return
        }

        options.onError?.(e.message || '网络异常')
        throw e
      }
    },
    [options],
  )

  const runDebounced = useCallback(
    (params: SandboxRunParams, delayMs: number = options.debounceMs ?? 300) => {
      // Clear previous debounce timer
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }

      // Set new debounce timer
      debounceTimerRef.current = setTimeout(() => {
        run(params)
      }, delayMs)
    },
    [run, options.debounceMs],
  )

  const cancel = useCallback(() => {
    // Abort in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    // Clear debounce timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
  }, [])

  return {
    run,
    runDebounced,
    cancel,
  }
}
