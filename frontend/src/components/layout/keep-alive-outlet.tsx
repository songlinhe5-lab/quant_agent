/**
 * FE-ARCH-01: 路由友好 Keep-Alive
 * 保留 URL 深链；已访问模块隐藏不卸载，减少行情/策略切换抖动。
 */
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { useLocation, useOutlet } from 'react-router-dom'
import { ModuleErrorBoundary } from '@/components/error-boundary'

const MAX_CACHED = 8

export function KeepAliveOutlet() {
  const outlet = useOutlet()
  const { pathname } = useLocation()
  const cacheRef = useRef(new Map<string, ReactElement>())
  const [, bump] = useState(0)

  useEffect(() => {
    if (!outlet) return

    const cache = cacheRef.current
    cache.set(pathname, outlet)

    if (cache.size > MAX_CACHED) {
      for (const key of cache.keys()) {
        if (key === pathname) continue
        cache.delete(key)
        if (cache.size <= MAX_CACHED) break
      }
    }

    bump((n) => n + 1)
  }, [pathname, outlet])

  const entries = Array.from(cacheRef.current.entries())

  return (
    <>
      {entries.map(([path, el]) => {
        const active = path === pathname
        return (
          <div
            key={path}
            className={active ? 'h-full' : 'hidden'}
            aria-hidden={!active}
            data-keep-alive-path={path}
          >
            <ModuleErrorBoundary name={path}>{el}</ModuleErrorBoundary>
          </div>
        )
      })}
    </>
  )
}
