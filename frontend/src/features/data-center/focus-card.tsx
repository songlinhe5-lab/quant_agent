'use client'

import React from 'react'

/** UIRF-15: 数据中心概览通用卡片（从 data-center-overview.tsx 拆分） */
export function FocusCard({
  title, badge, moreLabel, onMore, empty, emptyText, footerNote, children,
}: {
  title: string
  badge?: string
  moreLabel?: string
  onMore?: () => void
  empty: boolean
  emptyText: string
  footerNote?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col">
      {/* 标题区：纯标题 + badge 右对齐（对齐 Figma 设计稿） */}
      <div className="px-4 py-3 border-b border-border/30 flex items-center gap-2">
        <span className="text-[13px] font-semibold text-foreground">{title}</span>
        {badge && (
          <span className="ml-auto text-[10px] font-mono text-muted-foreground/70">{badge}</span>
        )}
      </div>
      {/* 内容区 */}
      <div className="px-4 py-3 flex-1">
        {empty ? <div className="text-[11px] text-muted-foreground/70 py-4 text-center">{emptyText}</div> : children}
      </div>
      {/* 底部 footer：左按钮 + 右说明文字（对齐设计稿） */}
      {(onMore || footerNote) && (
        <div className="px-4 py-3 border-t border-border/20 flex items-center justify-between gap-2">
          {onMore ? (
            <button
              onClick={onMore}
              className="px-3 py-1 rounded-full border border-foreground/40 text-[11px] text-foreground hover:bg-secondary/40 transition-colors"
            >
              {moreLabel || '更多 →'}
            </button>
          ) : <span />}
          {footerNote && <span className="text-[10px] text-muted-foreground/80 text-right">{footerNote}</span>}
        </div>
      )}
    </div>
  )
}
