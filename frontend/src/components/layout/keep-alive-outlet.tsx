/**
 * FE-ARCH-01: 路由友好 Keep-Alive
 * 保留 URL 深链；已访问模块隐藏不卸载，减少行情/策略切换抖动。
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactElement } from 'react'
import { useLocation, useOutlet } from 'react-router-dom'
import { ModuleErrorBoundary } from '@/components/error-boundary'

const MAX_CACHED = 8

/**
 * Keep-Alive 激活态上下文：告知被缓存（隐藏但未卸载）的模块当前是否为激活路由。
 * WS / 轮询等副作用应据此在后台模块中暂停，避免多模块 WS 并发重连风暴。
 */
export const KeepAliveActiveContext = createContext<boolean>(true)
export const useKeepAliveActive = () => useContext(KeepAliveActiveContext)

export function KeepAliveOutlet() {
  const outlet = useOutlet()
  const { pathname } = useLocation()
  const cacheRef = useRef(new Map<string, ReactElement>())
  // useOutlet() 每次渲染都会返回一个新的 element 引用，若直接放进 effect 依赖数组会
  // 触发 "Maximum update depth exceeded" 无限渲染循环（effect -> bump -> 重渲染 -> 新 outlet -> effect）。
  // 改用 ref 读取最新 outlet，effect 仅在 pathname 变化时执行。
  const outletRef = useRef(outlet)
  outletRef.current = outlet
  const [, bump] = useState(0)

  useEffect(() => {
    if (!outletRef.current) return

    const cache = cacheRef.current
    cache.set(pathname, outletRef.current)

    if (cache.size > MAX_CACHED) {
      for (const key of cache.keys()) {
        if (key === pathname) continue
        cache.delete(key)
        if (cache.size <= MAX_CACHED) break
      }
    }

    bump((n) => n + 1)
  }, [pathname])

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
            {/* ⚠️ 通过 context 把"是否激活"下发给模块，后台隐藏模块据此暂停 WS */}
            <KeepAliveActiveContext.Provider value={active}>
              <ModuleErrorBoundary name={path}>{el}</ModuleErrorBoundary>
            </KeepAliveActiveContext.Provider>
          </div>
        )
      })}
    </>
  )
}
