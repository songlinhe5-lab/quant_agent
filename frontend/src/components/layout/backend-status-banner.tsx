import React, { useEffect, useState } from 'react'
import { WifiOff, RefreshCw } from 'lucide-react'
import { useBackendStatusStore } from '@/stores/useBackendStatusStore'
import { API_BASE_URL } from '@/lib/api-client'
import { cn } from '@/lib/utils'

/**
 * FE-NET-01: 后端不可达全局横幅。
 * 由 useBackendStatusStore 驱动：连续 3 次网络层失败 → offline → 顶部红色提示。
 * 离线期间每 15s 静默探活（绕过 apiClient 避免重复打点），后端恢复后自动消失。
 */
export function BackendStatusBanner() {
  const status = useBackendStatusStore((s) => s.status)
  const lastError = useBackendStatusStore((s) => s.lastError)
  const reset = useBackendStatusStore((s) => s.reset)
  const [probing, setProbing] = useState(false)

  // 离线时静默轮询探活，后端恢复后 registerSuccess 会自动隐藏横幅
  useEffect(() => {
    if (status !== 'offline') return
    let alive = true
    const probe = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/health`, { method: 'GET', credentials: 'include' })
        if (alive && res.ok) useBackendStatusStore.getState().registerSuccess()
      } catch {
        /* 仍离线，忽略 */
      }
    }
    const iv = setInterval(probe, 15000)
    return () => {
      alive = false
      clearInterval(iv)
    }
  }, [status])

  if (status !== 'offline') return null

  const handleRetry = async () => {
    setProbing(true)
    try {
      const res = await fetch(`${API_BASE_URL}/health`, { method: 'GET', credentials: 'include' })
      if (res.ok) useBackendStatusStore.getState().registerSuccess()
      else reset() // 仍未恢复，复位计数给用户片刻喘息
    } catch {
      reset()
    } finally {
      setProbing(false)
    }
  }

  return (
    <div
      role="alert"
      className="flex items-center gap-3 px-4 h-9 shrink-0 bg-red-500/15 border-b border-red-500/40 text-red-300 text-xs z-50"
    >
      <WifiOff className="h-4 w-4 shrink-0 text-red-400" aria-hidden />
      <span className="font-semibold text-red-200 shrink-0">无法连接服务器</span>
      <span className="text-red-300/70 hidden sm:inline truncate">
        后端不可达，请检查网络或浏览器代理设置{lastError ? `（${lastError}）` : ''}
      </span>
      <button
        type="button"
        onClick={handleRetry}
        disabled={probing}
        className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md bg-red-500/20 hover:bg-red-500/30 text-red-200 transition-colors disabled:opacity-50 shrink-0"
        aria-label="重试连接"
      >
        <RefreshCw className={cn('h-3 w-3', probing && 'animate-spin')} />
        重试
      </button>
    </div>
  )
}
