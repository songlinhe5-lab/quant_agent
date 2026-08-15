/**
 * API Client 三通道封装 (REST / WS / SSE)
 * FE-16: 统一 baseURL、错误码处理、请求拦截器自动用 Refresh Token 续期 Access Token
 * SEC-07: Access Token 仅存于内存，Refresh Token 由 HttpOnly Cookie 自动携带
 */

import type { ApiResponse } from '@/types/domain'
import logger from '@/lib/logger'
import { useBackendStatusStore } from '@/stores/useBackendStatusStore'

// ─── 配置 ──────────────────────────────────────────────────────────
const API_VERSION = import.meta.env.VITE_API_URL_VERSION || 'v1';
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `/api/${API_VERSION}`

/**
 * 推导 WebSocket 基址，使其跟随 REST 的 API 域名（VITE_API_BASE_URL），
 * 而非 window.location.host。避免前端访问域名（如 quant.stephenhe.com）的
 * /api/* 被 Cloudflare 拦截导致 WS 连不上。
 * - 绝对 URL（http/https）→ 替换为 ws/wss 并去掉路径，仅保留 origin
 * - 相对路径（/api/v1）→ 回退到 window.location 协议+host（dev proxy 场景）
 */
export function getWsBaseUrl(): string {
  try {
    if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
      const u = new URL(API_BASE_URL)
      const wsProtocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${wsProtocol}//${u.host}`
    }
  } catch {
    /* fallthrough */
  }
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${wsProtocol}//${window.location.host}`
}

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

// ─── Token 管理（localStorage 持久化）─────────────────────────────────
const TOKEN_KEY = 'quant_access_token'

// 登录态彻底失效（Refresh Token 也被服务端拒绝）时触发的回调。
// 由 auth-context 在挂载时注册，统一跳转到登录页，避免在多个请求里各自散弹式处理。
let authRequiredHandler: (() => void) | null = null
export function setAuthRequiredHandler(handler: (() => void) | null) {
  authRequiredHandler = handler
}
function emitAuthRequired() {
  if (authRequiredHandler) {
    try { authRequiredHandler() } catch { /* 防止回调异常影响请求流 */ }
  }
}
// 供无 401 拦截器的裸 fetch 场景（如 chat 流）在捕获到认证失效时主动触发重登
export { emitAuthRequired }

/**
 * 获取 Access Token（从 localStorage）
 */
export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(TOKEN_KEY)
}

/**
 * 设置 Access Token（写入 localStorage）
 */
export function setAccessToken(token: string | null): void {
  if (typeof window === 'undefined') return
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token)
  } else {
    window.localStorage.removeItem(TOKEN_KEY)
  }
}

/**
 * 清除 Token
 */
export function clearTokens(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(TOKEN_KEY)
}

// 防止并发刷新
let tokenRefreshPromise: Promise<string | null> | null = null
// 标记刷新接口是否因"真 401（Refresh Token 失效）"而失败；
// 网络/跨域异常导致刷新失败时保持 false，避免瞬时错误注销用户。
let lastRefreshFailedHard = false

/**
 * 底层刷新 Access Token（模块级，供 REST 拦截器与 WebSocket 复用）
 * - Refresh Token 通过 HttpOnly Cookie 自动携带（credentials: 'include'）
 * - 返回新 token；失败则清除本地 token 并返回 null
 */
async function doRefreshToken(config: ClientConfig): Promise<string | null> {
  if (tokenRefreshPromise) return tokenRefreshPromise

  tokenRefreshPromise = (async () => {
    try {
      const response = await fetch(`${config.baseURL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include', // Refresh Token 在 HttpOnly Cookie
      })

      if (!response.ok) {
        // 仅当刷新接口本身明确拒绝（4xx 尤其是 401）才清 token 跳登录；
        // 网络/跨域拦截等异常不应立即注销用户，交由有限重试兜底。
        if (response.status === 401) {
          clearTokens()
          lastRefreshFailedHard = true
        }
        return null
      }

      const data = await response.json()
      const newToken = data.data?.access_token || data.access_token
      if (newToken) {
        setAccessToken(newToken)
        lastRefreshFailedHard = false
        logger.info('[API] Token 刷新成功')
        return newToken
      }
      return null
    } catch (error) {
      // 网络异常 / 跨域被拦截（如 CF 返回非 JSON 拦截页）：不清 token，允许下次重试
      lastRefreshFailedHard = false
      logger.error('[API] Token 刷新请求异常（非 401，保留会话）', error as Error)
      return null
    } finally {
      tokenRefreshPromise = null
    }
  })()

  return tokenRefreshPromise
}

/**
 * 解析 JWT 的 exp（秒级时间戳）；解析失败返回 null
 */
export function getTokenExp(token: string | null): number | null {
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

/**
 * 判断 token 是否已过期或将在 skew 秒内过期（默认提前 60s 续期）
 */
export function isTokenExpired(token: string | null, skew = 60): boolean {
  const exp = getTokenExp(token)
  if (exp === null) return true
  return Math.floor(Date.now() / 1000) >= exp - skew
}

/**
 * 公共刷新入口：供 WebSocket 等无 401 拦截器的场景主动续期 Access Token
 */
export async function refreshAccessToken(): Promise<string | null> {
  return doRefreshToken(DEFAULT_CONFIG)
}

/**
 * 🔑 统一 Token 获取入口（唯一推荐）
 *
 * 所有需要 Access Token 的场景（REST / WS / SSE）均应调用此函数，
 * 内部自动处理过期检测 + Refresh Token 续期，调用方无需关心刷新逻辑。
 *
 * @returns 有效的 Access Token；若未登录或 Refresh Token 也失效则返回 null
 */
export async function getValidAccessToken(): Promise<string | null> {
  const token = getAccessToken()
  if (!token) return null
  if (!isTokenExpired(token)) return token
  // Token 已过期或即将过期 → 静默续期
  return doRefreshToken(DEFAULT_CONFIG)
}

/**
 * 带自动续期的 fetch 封装（裸 fetch 统一入口）
 * - 复用 getValidAccessToken 预先检测过期并静默续期（默认续期）
 * - 若仍收到 401（极端场景：服务端时钟偏移 / 超长流式连接越过 TTL / token 被吊销），
 *   走 refreshAccessToken 强制刷新一次并重试，对齐 apiClient.request 的 401 重试语义
 * - 自动拼接 Bearer；默认带 credentials: 'include'（与 apiClient 一致）
 *
 * 适用于不走 apiClient 的裸 fetch（流式策略生成、普通请求等）。
 */
export async function fetchWithAuth(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getValidAccessToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const doFetch = (authToken: string | null): Promise<Response> => {
    const h = new Headers(headers)
    if (authToken) h.set('Authorization', `Bearer ${authToken}`)
    return fetch(url, { ...init, headers: h, credentials: init.credentials ?? 'include' })
  }

  // 401 自愈：最多重试 2 轮（每次先强制 refresh，再带新 token 重发）。
  // - Refresh 成功但重发仍 401（极端：token 刚被吊销）→ 跳出，交给上层
  // - Refresh 本身被服务端明确拒绝（lastRefreshFailedHard）→ 立即触发重登
  let res = await doFetch(token)
  if (res.status === 401) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const refreshed = await refreshAccessToken()
      if (!refreshed) {
        // refresh 失败：若服务端明确拒绝（Refresh Token 失效），直接跳登录
        if (lastRefreshFailedHard) {
          clearTokens()
          emitAuthRequired()
        }
        break
      }
      res = await doFetch(refreshed)
      if (res.status !== 401) break
    }
    // 两次重试后仍是 401，且 refresh 未被硬拒绝（瞬时跨域/网络）→ 不再死循环
    if (res.status === 401 && lastRefreshFailedHard) {
      clearTokens()
      emitAuthRequired()
    }
  }
  return res
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

    // 添加 Access Token（统一入口 getValidAccessToken：自动检测过期并静默续期，见 FE-16/SEC-07）
    const token = await getValidAccessToken()
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
        body: body instanceof URLSearchParams
          ? body
          : body
            ? JSON.stringify(body)
            : undefined,
        credentials: this.config.withCredentials ? 'include' : 'omit',
        signal: signal || controller.signal,
      })

      clearTimeout(timeoutId)

      // 拿到任意 HTTP 响应（含 4xx/5xx）均说明后端在线 → 复位可达性状态、隐藏离线横幅
      useBackendStatusStore.getState().registerSuccess()

      // 处理 401 - 尝试刷新 Token
      if (response.status === 401) {
        // 仅 refresh/login 接口本身返回 401 → 说明 Refresh Token 也失效了，清除并跳转登录
        if (path === '/auth/refresh' || path === '/auth/login') {
          clearTokens()
          emitAuthRequired() // 统一出口：跳登录页（由 auth-context 注册）
          throw new ApiError(401, '认证失败')
        }

        const newToken = await this.refreshToken()
        if (newToken) {
          // 重试请求
          requestHeaders['Authorization'] = `Bearer ${newToken}`
          const retryResponse = await fetch(url, {
            method,
            headers: requestHeaders,
            body: body instanceof URLSearchParams
              ? body
              : body
                ? JSON.stringify(body)
                : undefined,
            credentials: this.config.withCredentials ? 'include' : 'omit',
            signal: signal || controller.signal,
          })
          return this.handleResponse<T>(retryResponse)
        }
        // 刷新失败：仅当刷新接口"真 401（Refresh Token 失效）"才清 token + 跳登录；
        // 网络/跨域瞬时异常不清 token，由后续请求重试续期，避免误踢用户。
        if (lastRefreshFailedHard) {
          clearTokens()
          emitAuthRequired() // 统一出口：跳登录页（由 auth-context 注册）
        }
        throw new ApiError(401, '认证已过期')
      }

      return this.handleResponse<T>(response)
    } catch (error) {
      clearTimeout(timeoutId)

      if (error instanceof DOMException && error.name === 'AbortError') {
        // 超时 = 后端无响应，计入网络层失败
        useBackendStatusStore.getState().registerFailure('请求超时')
        throw new ApiError(408, '请求超时')
      }

      if (error instanceof ApiError) throw error

      // 其余（TypeError: Failed to fetch / 代理连接失败 / 网络断开）均视为后端不可达
      const msg = (error as Error)?.message || '网络异常'
      useBackendStatusStore.getState().registerFailure(msg)
      logger.error('[API] 请求失败', error as Error, { method, path })
      throw new ApiError(500, '网络异常')
    }
  }

  /**
   * 处理响应 — 返回 axios 兼容格式 `{ data, status }`
   * - 标准格式 `{code, msg, data, ts}` → `res.data` = `apiData.data`（解包一层）
   * - 非标准格式 → `res.data` = 原始 JSON body
   * 前端统一通过 `res.data` 访问，与 axios 行为一致。
   * 注意：401/403 的 refresh 逻辑统一在 request() 中处理，此处仅抛错。
   */
  private async handleResponse<T>(response: Response): Promise<T> {
    const rawBody = await response.json()

    // 检查统一响应结构 { code, msg, data, ts }
    if (rawBody && typeof rawBody === 'object' && 'code' in rawBody) {
      const apiData = rawBody as ApiResponse<unknown>
      if (apiData.code !== 0 && apiData.code !== 200) {
        throw new ApiError(apiData.code, apiData.msg || '请求失败', apiData.data)
      }
      // 标准格式：解包 {code, data} → res.data = apiData.data
      return { data: apiData.data, status: response.status } as unknown as T
    }

    // 非标准响应
    if (!response.ok) {
      throw new ApiError(response.status, `HTTP ${response.status}`)
    }

    // 非标准格式：res.data = 原始 JSON body
    return { data: rawBody, status: response.status } as unknown as T
  }

  /**
   * 刷新 Access Token（委托给模块级 doRefreshToken）
   */
  private async refreshToken(): Promise<string | null> {
    return doRefreshToken(this.config)
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

  /**
   * 原始流式请求(POST + NDJSON)：返回未解包的 Response，供调用方按行读取流。
   * 用于 AI-02 解盘副驾 /ai/stream。
   */
  async stream(path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
    const url = `${this.config.baseURL}${path}`
    const requestHeaders: HeadersInit = { 'Content-Type': 'application/json' }
    const token = await getValidAccessToken()
    if (token) (requestHeaders as Record<string, string>)['Authorization'] = `Bearer ${token}`
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: requestHeaders,
        body: body ? JSON.stringify(body) : undefined,
        credentials: this.config.withCredentials ? 'include' : 'omit',
        signal,
      })
      if (!response.ok) {
        useBackendStatusStore.getState().registerFailure(`流式请求失败 ${response.status}`)
        throw new ApiError(response.status, `HTTP ${response.status}`)
      }
      useBackendStatusStore.getState().registerSuccess()
      return response
    } catch (error) {
      if (error instanceof ApiError) throw error
      const msg = (error as Error)?.message || '网络异常'
      useBackendStatusStore.getState().registerFailure(msg)
      throw new ApiError(500, '网络异常')
    }
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
      } catch (_e) {
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

  /** 原始流式请求(POST + NDJSON)：返回未解包的 Response，供按行读取流。用于 AI-02 解盘副驾 /ai/stream。 */
  stream(path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
    return this.rest.stream(path, body, signal)
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

// ─── 主动续期（Token Keep-Alive）────────────────────────────────
/**
 * 问题背景：原续期为"被动触发"——只有某次 REST 请求撞上 access token 过期窗口
 * 才会去 /auth/refresh。若页面长时间静止（仅 WS 推送、无 REST 请求），access token
 * 过期后下一次任意请求才续期；一旦刷新接口因瞬时网络/跨域失败，就会被立即清 token 踢回登录页。
 *
 * 这里改为"主动保活"：依据 access token 的 exp 提前续期，并在页面重新可见时兜底续期，
 * 避免静止超时 + 被动续期偶发失败导致被踢。
 */
let keepAliveTimer: ReturnType<typeof setTimeout> | null = null
let keepAliveBound = false

function scheduleNextRefresh() {
  if (keepAliveTimer) clearTimeout(keepAliveTimer)
  const token = getAccessToken()
  if (!token) return // 未登录，停止
  const exp = getTokenExp(token)
  if (exp === null) return
  const now = Math.floor(Date.now() / 1000)
  // 距过期还剩多少秒；exp - now 为剩余有效期
  const remain = exp - now
  if (remain <= 0) {
    // 已过期，立即续期
    void getValidAccessToken()
    scheduleNextRefresh()
    return
  }
  // 提前 120s 续期（不足 120s 则立即续期）
  const delayMs = Math.max(0, (remain - 120)) * 1000
  keepAliveTimer = setTimeout(async () => {
    await getValidAccessToken()
    scheduleNextRefresh()
  }, delayMs)
}

function onVisibilityChange() {
  if (document.visibilityState !== 'visible') return
  const token = getAccessToken()
  if (!token) return
  const exp = getTokenExp(token)
  if (exp !== null) {
    const remain = exp - Math.floor(Date.now() / 1000)
    // 页面重新可见且 5 分钟内将过期 → 立即兜底续期
    if (remain <= 300) {
      void getValidAccessToken().then(() => scheduleNextRefresh())
      return
    }
  }
  scheduleNextRefresh()
}

/**
 * 启动 token 主动保活。应在登录成功后调用（auth-context 挂载时）。
 */
export function startTokenKeepAlive() {
  if (!keepAliveBound) {
    document.addEventListener('visibilitychange', onVisibilityChange)
    keepAliveBound = true
  }
  scheduleNextRefresh()
}

/** 停止保活（登出时调用） */
export function stopTokenKeepAlive() {
  if (keepAliveTimer) clearTimeout(keepAliveTimer)
  keepAliveTimer = null
  if (keepAliveBound) {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    keepAliveBound = false
  }
}
