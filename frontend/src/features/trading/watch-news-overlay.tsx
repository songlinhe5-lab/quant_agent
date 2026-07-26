'use client'

import { useState } from 'react'
import { Newspaper, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MarketNewsPanel } from './market-news-panel'

/**
 * PROD-05 深化（进阶建议 1）：盯盘全屏场景的可折叠新闻流浮层。
 * - 默认收起，仅右上角一个展开钮，不破坏 K 线全屏的聚焦体验；
 * - 仅 ≥1920px 由 `min-[1920px]:` 任意媒体变体揭示（小屏聚焦模式彻底无干扰）；
 * - 浮层锚定在右侧盘口悬浮（w-72）左侧，避免与盘口/自选球重叠；
 * - 外层 pointer-events-none，仅按钮与展开面板可交互，K 线拖拽不受影响。
 */
export function WatchNewsOverlay() {
  const [open, setOpen] = useState(false)

  return (
    <div className="absolute top-3 right-[19.5rem] bottom-3 z-30 flex flex-col items-end gap-2 max-[640px]:hidden pointer-events-none">
      {/* 展开/收起按钮：仅 ≥1920px 可见 */}
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'pointer-events-auto hidden min-[1920px]:flex items-center gap-1.5 h-8 px-3 rounded-lg glass-card border border-border/40 text-[11px] font-semibold text-muted-foreground hover:text-foreground hover:border-scene/50 transition-colors shadow-lg shrink-0',
          open && 'text-foreground border-scene/50',
        )}
        title="新闻流（≥1920px 可用）"
      >
        <Newspaper className="h-3.5 w-3.5" />
        {open ? '收起新闻' : '新闻流'}
      </button>

      {/* 展开的新闻浮层：默认收起；≥1920px 才渲染可见 */}
      {open && (
        <div className="pointer-events-auto hidden min-[1920px]:flex flex-1 mt-1 w-[340px] flex-col glass-card rounded-xl overflow-hidden border border-border/40 shadow-2xl">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border/40 bg-secondary/20 shrink-0">
            <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">宏观新闻流</span>
            <button
              onClick={() => setOpen(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label="收起新闻流"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 min-h-0">
            <MarketNewsPanel />
          </div>
        </div>
      )}
    </div>
  )
}
