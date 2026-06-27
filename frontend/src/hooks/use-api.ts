'use client'

import { useState, useCallback } from 'react'
import axios, { AxiosRequestConfig, AxiosError } from 'axios'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'

type AxiosOptions = AxiosRequestConfig & {
  // 是否在请求失败时自动弹出 Toast 提示（默认 true）
  showToastOnError?: boolean
}

export function useApi<T = any>() {
  const { toast } = useToast()
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | AxiosError | null>(null)

  const execute = useCallback(
    async (url: string, options: AxiosOptions = {}) => {
      const { showToastOnError = true, ...axiosOptions } = options

      setIsLoading(true)
      setError(null)

      try {
        // 使用全局配置好 baseURL 和拦截器的 apiClient 发起请求
        const response = await apiClient({ url, ...axiosOptions })
        setData(response.data)
        return response.data as T
      } catch (err: any) {
        const e = err instanceof Error ? err : new Error(String(err))
        setError(e)
        
        // 判断是否为 401 未授权错误
        const isUnauthorized = axios.isAxiosError(err) && err.response?.status === 401

        // 从 Axios 错误中提取后端返回的详细错误信息
        let errorMessage = e.message
        if (axios.isAxiosError(err) && err.response?.data) {
          const responseData = err.response.data as any
          errorMessage = responseData.message || responseData.detail || errorMessage
        }

        // 统一的错误拦截与提示（如果是 401 则静默处理，交由 apiClient 去跳转页面）
        if (showToastOnError && !isUnauthorized) {
          toast({
            variant: 'destructive',
            title: '请求失败',
            description: errorMessage || '网络连接异常，请稍后重试。',
          })
        }
        
        throw e // 抛出错误以便业务层继续捕获（如果需要）
      } finally {
        setIsLoading(false)
      }
    },
    [toast]
  )

  return {
    data,
    isLoading,
    error,
    execute,
  }
}