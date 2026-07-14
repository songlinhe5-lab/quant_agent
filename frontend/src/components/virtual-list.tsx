'use client'

import { useRef } from 'react'
import { useVirtualizer } from './use-virtualizer-lite'

type VirtualListProps<T> = {
  items: T[]
  estimateSize?: number
  className?: string
  height?: number | string
  renderItem: (item: T, index: number) => React.ReactNode
  getKey?: (item: T, index: number) => string | number
}

/** FE-13: 固定行高虚拟列表 */
export function VirtualList<T>({
  items,
  estimateSize = 44,
  className,
  height = '100%',
  renderItem,
  getKey,
}: VirtualListProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize,
  })

  return (
    <div
      ref={parentRef}
      className={className}
      style={{ height, overflow: 'auto' }}
      data-testid="virtual-list"
    >
      <div
        style={{
          height: `${rowVirtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const item = items[virtualRow.index]
          return (
            <div
              key={getKey ? getKey(item, virtualRow.index) : virtualRow.key}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {renderItem(item, virtualRow.index)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
