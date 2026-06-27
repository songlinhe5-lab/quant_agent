import axios from 'axios'

// 暴露 API 基础路径，供 fetch 等原生请求拼接完整 URL
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || '/api'

// 创建全局 Axios 实例
export const apiClient = axios.create({
  baseURL: API_BASE_URL, 
  timeout: 30000,
  // 💡 关键点：跨域时允许携带 HttpOnly Cookie
  withCredentials: true,
})

// ── 内存 Token 管理 ────────────────────────────────────────────────────────

let currentAccessToken: string | null = null

// 暴露设置 Token 的方法，供登录组件和 AuthContext 使用
export const setAccessToken = (token: string | null) => {
  currentAccessToken = token
}

// 暴露获取 Token 的方法，供原生的 fetch 或 WebSocket 使用
export const getAccessToken = () => {
  return currentAccessToken
}

// ── 并发刷新队列管理 ────────────────────────────────────────────────────────
// 当页面加载并发发出多个请求，遇到 401 时，防止多次触发刷新接口

let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: any) => void }> = []

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token as string)
    }
  })
  failedQueue = []
}

// ── 拦截器配置 ──────────────────────────────────────────────────────────────

apiClient.interceptors.request.use(
  (config) => {
    // 从 React 内存中获取短期 Access Token
    if (currentAccessToken && config.headers) {
      config.headers.Authorization = `Bearer ${currentAccessToken}`
    }
    
    // 💡 针对大模型对话和会话管理接口，单独放宽超时限制至 2 分钟 (120000ms)，或者设为 0（不限制超时）
    if (config.url?.includes('/chat') || config.url?.includes('/sessions')) {
      config.timeout = 120000
    }

    return config
  },
  (error) => Promise.reject(error)
)

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // 🚨 核心修复：如果是登录接口或刷新接口自身的 401 报错，说明是密码错误或刷新凭证彻底失效
    // 直接抛出错误让前端业务代码（如 login.tsx）处理，绝对不要触发无限无感刷新重试
    if (originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/refresh')) {
      return Promise.reject(error)
    }

    // 捕获 401 未授权错误，且请求尚未重试过
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // 如果当前正在刷新 Token，将当前请求加入队列排队等待
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return apiClient(originalRequest)
        }).catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        // 尝试无感刷新：向后端请求获取新的 Access Token
        // 💡 浏览器会自动携带 HttpOnly Cookie 中的 Refresh Token
        // 修复：原生 axios 请求必须显式拼接 API_BASE_URL，否则缺少 /api 前缀报 404
        const { data } = await axios.post(`${API_BASE_URL}/auth/refresh`, {}, { withCredentials: true })
        const newAccessToken = data.access_token

        setAccessToken(newAccessToken)
        processQueue(null, newAccessToken)

        // 带着新的 Token 重发原本失败的请求
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
        return apiClient(originalRequest)
      } catch (refreshError) {
        // 刷新失败（Refresh Token 也过期了或者非法）
        processQueue(refreshError, null)
        setAccessToken(null)

        // 避免在登录页面无限跳转
        if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
          // 携带当前完整路径和查询参数，这样登录成功后可以无缝跳转回来
          // 临时注释掉跳转逻辑，以便在开发数据看板时忽略登录拦截
          // const currentPath = window.location.pathname + window.location.search;
          // window.location.href = `/login?from=${encodeURIComponent(currentPath)}`;
        }
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)