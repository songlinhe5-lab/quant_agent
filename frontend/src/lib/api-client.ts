/**
 * API Client 三通道封装 (REST / WS / SSE)
 * FE-16: 统一 baseURL、错误码处理、请求拦截器自动用 Refresh Token 续期 Access Token
 * SEC-07: Access Token 仅存于内存，Refresh Token 由 HttpOnly Cookie 自动携带
 */

import type { ApiResponse } from '@/types/domain'
import logger from '@/lib/logger'

// ─── 配置 ──────────────────────────────────────────────────────────
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

interface ClientConfig {
  baseURL: string
  timeout: number
  withCredentials: boolean
}

const DEFAULT_CONFIG: ClientConfig = {
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
}

// ─── Token 管理（内存存储，SEC-07）─────────────────────────────────
let currentAccessToken: string | null = null
let tokenRefreshPromise: Promise<string> | null = null

/**
 * 获取 Access Token（仅内存）
 */
export function getAccessToken(): string | null {
  return currentAccessToken
}

/**
 * 设置 Access Token
 */
export function setAccessToken(token: string | null): void {
  currentAccessToken = token
}

/**
 * 清除 Token
 */
export function clearTokens(): void {
  currentAccessToken = null
}

// ─── 错误类 ────────────────────────────────────────────────────────
export class ApiError extends Error {
  code: number
  data?: unknown
  
  constructor(code: number, message: string, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
  }
}

// ─── REST Client ───────────────────────────────────────────────────
class RestClient {
  private config: ClientConfig

  constructor(config: ClientConfig) {
    this.config = config
  }

  /**
   * 发起 HTTP 请求
   */
  async request<T = any>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH',
    path: string,
    options: {
      body?: unknown
      params?: Record<string, any>
      headers?: Record<string, string>
      signal?: AbortSignal
    } = {}
  ): Promise<T> {
    const { body, params, headers = {}, signal } = options

    // 构建 URL
    let url = `${this.config.baseURL}${path}`
    if (params) {
      const searchParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) searchParams.append(key, String(value))
      })
      const qs = searchParams.toString()
      if (qs) url += `?${qs}`
    }

    // 构建请求头
    const requestHeaders: HeadersInit = {
      'Content-Type': 'application/json',
      ...headers,
    }

    // 添加 Access Token
    const token = getAccessToken()
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`
    }

    // 发起请求
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeout)
    
    try {
      const response = await fetch(url, {
        method,
        headers: requestHeaders,
        body: body ? JSON.stringify(body) : undefined,
        credentials: this.config.withCredentials ? 'include' : 'omit',
        signal: signal || controller.signal,
      })

      clearTimeout(timeoutId)

      // 处理 401 - 尝试刷新 Token
      if (response.status === 401) {
        const newToken = await this.refreshToken()
        if (newToken) {
          // 重试请求
          requestHeaders['Authorization'] = `Bearer ${newToken}`
          const retryResponse = await fetch(url, {
            method,
            headers: requestHeaders,
            body: body ? JSON.stringify(body) : undefined,
            credentials: this.config.withCredentials ? 'include' : 'omit',
            signal: signal || controller.signal,
          })
          return this.handleResponse<T>(retryResponse)
        }
        // 刷新失败，跳转登录
        window.location.href = '/login'
        throw new ApiError(401, '认证已过期')
      }

      return this.handleResponse<T>(response)
    } catch (error) {
      clearTimeout(timeoutId)
      
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError(408, '请求超时')
      }
      
      if (error instanceof ApiError) throw error
      
      logger.error('[API] 请求失败', error as Error, { method, path })
      throw new ApiError(500, '网络异常')
    }
  }

  /**
   * 处理响应
   */
  private async handleResponse<T>(response: Response): Promise<T> {
    const data = await response.json()
    
    // 检查统一响应结构 { code, msg, data, ts }
    if (data && typeof data === 'object' && 'code' in data) {
      const apiData = data as ApiResponse<T>
      if (apiData.code !== 0 && apiData.code !== 200) {
        throw new ApiError(apiData.code, apiData.msg || '请求失败', apiData.data)
      }
      return apiData.data as T
    }

    // 非标准响应，直接返回
    if (!response.ok) {
      throw new ApiError(response.status, `HTTP ${response.status}`)
    }

    return data as T
  }

  /**
   * 刷新 Access Token
   */
  private async refreshToken(): Promise<string | null> {
    // 防止并发刷新
    if (tokenRefreshPromise) return tokenRefreshPromise

    tokenRefreshPromise = (async () => {
      try {
        const response = await fetch(`${this.config.baseURL}/auth/refresh`, {
          method: 'POST',
          credentials: 'include', // Refresh Token 在 HttpOnly Cookie
        })

        if (!response.ok) {
          clearTokens()
          return null
        }

        const data = await response.json()
        const newToken = data.data?.access_token || data.access_token
        if (newToken) {
          setAccessToken(newToken)
          logger.info('[API] Token 刷新成功')
          return newToken
        }
        return null
      } catch (error) {
        logger.error('[API] Token 刷新失败', error as Error)
        clearTokens()
        return null
      } finally {
        tokenRefreshPromise = null
      }
    })()

    return tokenRefreshPromise
  }

  // ─── 快捷方法 ─────────────────────────────────────────────────
  get<T = any>(path: string, params?: Record<string, any>, signal?: AbortSignal): Promise<T> {
    return this.request<T>('GET', path, { params, signal })
  }

  post<T = any>(path: string, body?: unknown, config?: { headers?: Record<string, string>; signal?: AbortSignal; timeout?: number }): Promise<T> {
    return this.request<T>('POST', path, { body, ...config })
  }

  put<T = any>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PUT', path, { body })
  }

  delete<T = any>(path: string, config?: { data?: unknown; signal?: AbortSignal }): Promise<T> {
    return this.request<T>('DELETE', path, { ...config })
  }

  patch<T = any>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PATCH', path, { body })
  }
}

// ─── SSE Client ────────────────────────────────────────────────────
class SSEClient {
  private config: ClientConfig
  private connections: Map<string, EventSource> = new Map()

  constructor(config: ClientConfig) {
    this.config = config
  }

  /**
   * 订阅 SSE 流
   */
  subscribe(
    path: string,
    onMessage: (data: unknown) => void,
    onError?: (error: Event) => void
  ): () => void {
    const url = `${this.config.baseURL}${path}`
    const key = url

    // 避免重复连接
    if (this.connections.has(key)) {
      this.connections.get(key)!.close()
    }

    const source = new EventSource(url, { withCredentials: true })
    this.connections.set(key, source)

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage(data)
      } catch (e) {
        logger.warn('[SSE] 消息解析失败', { raw: event.data })
      }
    }

    source.onerror = (event) => {
      logger.error('[SSE] 连接错误', event as unknown as Error)
      onError?.(event)
    }

    // 返回取消订阅函数
    return () => {
      source.close()
      this.connections.delete(key)
    }
  }

  /**
   * 关闭所有连接
   */
  closeAll(): void {
    this.connections.forEach((source) => source.close())
    this.connections.clear()
  }
}

// ─── 统一 API Client ───────────────────────────────────────────────
class UnifiedApiClient {
  public rest: RestClient
  public sse: SSEClient

  constructor(config: Partial<ClientConfig> = {}) {
    const mergedConfig = { ...DEFAULT_CONFIG, ...config }
    this.rest = new RestClient(mergedConfig)
    this.sse = new SSEClient(mergedConfig)
  }

  // REST 快捷方法
  get<T = any>(path: string, params?: Record<string, any>, signal?: AbortSignal): Promise<T> {
    return this.rest.get<T>(path, params, signal)
  }

  post<T = any>(path: string, body?: unknown, config?: { headers?: Record<string, string>; signal?: AbortSignal; timeout?: number }): Promise<T> {
    return this.rest.post<T>(path, body, config)
  }

  put<T = any>(path: string, body?: unknown): Promise<T> {
    return this.rest.put<T>(path, body)
  }

  delete<T = any>(path: string, config?: { data?: unknown; signal?: AbortSignal }): Promise<T> {
    return this.rest.delete<T>(path, config)
  }

  // SSE 快捷方法
  subscribe(path: string, onMessage: (data: unknown) => void, onError?: (error: Event) => void): () => void {
    return this.sse.subscribe(path, onMessage, onError)
  }
}

// ─── 导出单例 ──────────────────────────────────────────────────────
export const apiClient = new UnifiedApiClient()

// 默认导出
export default apiClient
