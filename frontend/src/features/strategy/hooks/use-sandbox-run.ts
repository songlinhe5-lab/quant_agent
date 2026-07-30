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

  const runStream = useCallback(
    async (
      params: SandboxRunParams,
      onProgress?: (p: { progress: number; stage: string; detail?: string }) => void,
      shouldAbort?: () => boolean,
    ) => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }

      const controller = new AbortController()
      abortControllerRef.current = controller

      const currentSeq = ++requestSeqRef.current

      try {
        const res = await apiClient.stream('/strategy/run-sandbox/stream', params, controller.signal)
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let finalResult: any = null

        while (true) {
          if (shouldAbort?.()) {
            controller.abort()
            break
          }
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          let nl: number
          while ((nl = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, nl).trim()
            buffer = buffer.slice(nl + 1)
            if (!line) continue

            let msg: any
            try {
              msg = JSON.parse(line)
            } catch {
              continue
            }
            if (msg.type === 'result') {
              finalResult = { status: 'success', data: msg.data }
            } else if (msg.type === 'error') {
              finalResult = { status: 'error', message: msg.message, error_code: msg.error_code }
            } else if (onProgress && typeof msg.progress === 'number') {
              onProgress({ progress: msg.progress, stage: msg.stage, detail: msg.detail })
            }
          }
        }

        if (currentSeq !== requestSeqRef.current) return finalResult
        if (finalResult?.status === 'success') {
          options.onSuccess?.(finalResult.data)
        } else if (finalResult?.status === 'error') {
          options.onError?.(finalResult.message)
        }
        return finalResult
      } catch (e: any) {
        if (e.name === 'CanceledError' || e.message === 'canceled') return
        if (currentSeq !== requestSeqRef.current) return
        options.onError?.(e.message || '网络异常')
        throw e
      }
    },
    [options],
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
    runStream,
    runDebounced,
    cancel,
  }
}
