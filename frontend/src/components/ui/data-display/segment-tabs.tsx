import { cn } from '@/lib/utils'

export interface SegmentItem {
  value: string
  label: string
}

interface SegmentTabsProps {
  items: SegmentItem[]
  value: string
  onChange: (value: string) => void
  className?: string
}

/**
 * 分段标签（设计稿「全部/股指/利率/外汇/商品/加密/行业ETF/类目自定义」pill 分组）。
 * 选中态白底反色，未选中米灰，复用 .segment-tabs 组件类（globals.css 令牌）。
 */
export function SegmentTabs({ items, value, onChange, className }: SegmentTabsProps) {
  return (
    <div className={cn('segment-tabs', className)} role="tablist">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={value === it.value}
          data-active={value === it.value}
          onClick={() => onChange(it.value)}
          className="seg-item"
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}
