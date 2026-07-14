/**
 * FE-13: 固定行高虚拟滚动 hook（无外部依赖）
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

type VirtualItem = {
  key: number
  index: number
  start: number
  size: number
}

export function useVirtualizer(opts: {
  count: number
  getScrollElement: () => HTMLElement | null
  estimateSize: number
  overscan?: number
}) {
  const { count, getScrollElement, estimateSize, overscan = 6 } = opts
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState(400)

  useEffect(() => {
    const el = getScrollElement()
    if (!el) return

    const onScroll = () => setScrollTop(el.scrollTop)
    const ro = new ResizeObserver(() => setViewport(el.clientHeight || 400))
    ro.observe(el)
    el.addEventListener('scroll', onScroll, { passive: true })
    setViewport(el.clientHeight || 400)
    setScrollTop(el.scrollTop)
    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
    }
  }, [getScrollElement])

  const getTotalSize = useCallback(() => count * estimateSize, [count, estimateSize])

  const getVirtualItems = useCallback((): VirtualItem[] => {
    if (count === 0) return []
    const startIndex = Math.max(0, Math.floor(scrollTop / estimateSize) - overscan)
    const endIndex = Math.min(
      count - 1,
      Math.ceil((scrollTop + viewport) / estimateSize) + overscan,
    )
    const items: VirtualItem[] = []
    for (let i = startIndex; i <= endIndex; i++) {
      items.push({
        key: i,
        index: i,
        start: i * estimateSize,
        size: estimateSize,
      })
    }
    return items
  }, [count, estimateSize, overscan, scrollTop, viewport])

  return useMemo(
    () => ({
      getTotalSize,
      getVirtualItems,
    }),
    [getTotalSize, getVirtualItems],
  )
}
