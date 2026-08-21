'use client'

import React, { useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import { Search, FileText, Scale, Trash2, X, Archive } from 'lucide-react'
import { useAssetLibrary, type AssetItem } from '@/stores/useAssetLibrary'
import { BriefingMarkdown } from '@/features/briefing/briefing-markdown'

const TYPE_META: Record<AssetItem['type'], { icon: string; label: string; cls: string }> = {
  chat: { icon: '📄', label: '对话导出', cls: 'bg-sky-500/10 text-sky-400 border-sky-500/20' },
  chief: { icon: '⚖️', label: '首席报告', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
}

function fmtDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })
}

/**
 * COPILOT-18: B2 资产库
 *  卡片列表(类型图标+标题+来源+日期) + 搜索 + 点开只读预览(Markdown)
 *  后端落库前无数据时显示 EmptyState
 */
export function AssetLibrary({ onClose }: { onClose: () => void }) {
  const items = useAssetLibrary((s) => s.items)
  const removeAsset = useAssetLibrary((s) => s.removeAsset)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<AssetItem | null>(null)

  const filtered = useMemo(
    () => items.filter((a) => (a.title + a.source).toLowerCase().includes(query.toLowerCase())),
    [items, query],
  )

  return (
    <div className="flex h-full flex-col">
      {/* 工具条 */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border/20 px-3">
        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          <Archive className="h-3 w-3" /> 资产库
        </span>
        <div className="relative ml-2 flex-1 max-w-[220px]">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索资产..."
            className="w-full rounded-md border border-border/40 bg-secondary/30 py-1 pl-6 pr-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:border-sky-500/50 focus:outline-none"
          />
        </div>
        <button type="button" onClick={onClose} className="ml-auto rounded p-1 text-muted-foreground hover:bg-secondary/60 hover:text-foreground" aria-label="关闭资产库">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* 卡片列表 */}
        <div className={cn('flex-1 min-w-0 overflow-y-auto p-3 custom-scrollbar', selected && 'hidden md:block')}>
          {items.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <div className="h-14 w-14 rounded-2xl bg-secondary/30 border border-border/40 flex items-center justify-center">
                <Archive className="h-7 w-7 text-muted-foreground/50" />
              </div>
              <p className="text-xs text-foreground/70">资产库还是空的</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground/70 max-w-[260px]">
                还没有沉淀的研究成果——完成一次投研会或导出对话后，这里会成为你的研究档案室
              </p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex h-full items-center justify-center text-[11px] text-muted-foreground">无匹配资产</div>
          ) : (
            <div className="space-y-2">
              {filtered.map((a) => {
                const meta = TYPE_META[a.type]
                return (
                  <div
                    key={a.id}
                    onClick={() => setSelected(a)}
                    className={cn(
                      'group cursor-pointer rounded-xl border border-border/30 bg-card/60 p-3 transition-colors hover:border-sky-500/30',
                      selected?.id === a.id && 'border-sky-500/40 bg-sky-500/5',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-base">{meta.icon}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-semibold text-foreground">{a.title}</div>
                        <div className="truncate text-[9px] text-muted-foreground">
                          {meta.label} · {fmtDate(a.date)}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); removeAsset(a.id); if (selected?.id === a.id) setSelected(null) }}
                        className="rounded p-1 text-muted-foreground opacity-0 transition-all hover:bg-red-500/15 hover:text-red-400 group-hover:opacity-100"
                        title="删除"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    <div className="mt-1.5 truncate pl-6 text-[9px] text-muted-foreground/60">来源：{a.source}</div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* 只读预览 */}
        {selected && (
          <div className="min-w-0 flex-1 overflow-y-auto border-l border-border/20 p-4 custom-scrollbar">
            <div className="mb-3 flex items-center gap-2">
              <span className="text-lg">{TYPE_META[selected.type].icon}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold text-foreground">{selected.title}</div>
                <div className="text-[9px] text-muted-foreground">{TYPE_META[selected.type].label} · 来源：{selected.source}</div>
              </div>
              <button type="button" onClick={() => setSelected(null)} className="rounded p-1 text-muted-foreground hover:bg-secondary/60" aria-label="关闭预览">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="rounded-lg border border-border/30 bg-secondary/10 p-3">
              <BriefingMarkdown content={selected.content} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
