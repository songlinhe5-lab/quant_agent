'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Plus, Search, Trash2, Loader2, Scale, Download, Inbox } from 'lucide-react'

interface ChatSession { session_id: string; title: string; created_at: string; updated_at: string; message_count: number }
interface DebateSession { session_id: string; scenario: string; question: string; status: string; expert_count: number; probability_assessment: number | null; created_at: string; completed_at: string }

export interface SessionItem {
  id: string
  kind: 'chat' | 'debate'
  title: string
  updatedAt: string
  bullish: number | null
  expertCount: number
}

type GroupKey = 'today' | 'week' | 'older'
const GROUP_META: Record<GroupKey, string> = { today: '今天', week: '近 7 天', older: '更早' }

function groupOf(iso: string): GroupKey {
  if (!iso) return 'older'
  let s = iso
  if (!s.endsWith('Z') && !s.match(/[+-]\d{2}:\d{2}$/)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return 'older'
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return 'today'
  return d >= new Date(now.getTime() - 7 * 864e5) ? 'week' : 'older'
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  let s = iso
  if (!s.endsWith('Z') && !s.match(/[+-]\d{2}:\d{2}$/)) s += 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function debateBadge(bullish: number | null): { label: string; cls: string } | null {
  if (bullish == null) return null
  if (bullish >= 60) return { label: `多 ${bullish}%`, cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' }
  if (bullish <= 40) return { label: `空 ${bullish}%`, cls: 'bg-red-500/15 text-red-400 border-red-500/30' }
  return { label: `中性 ${bullish}%`, cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' }
}

interface SessionCenterProps {
  activeId?: string
  onSelect: (item: SessionItem) => void
  onNewChat: () => void
}

export function SessionCenter({ activeId, onSelect, onNewChat }: SessionCenterProps) {
  const navigate = useNavigate()
  const [items, setItems] = useState<SessionItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setIsLoading(true)
    try {
      const [chatRes, debateRes] = await Promise.all([
        apiClient.get('/sessions').catch(() => ({ data: { status: 'error', data: [] } })),
        apiClient.get('/expert-team/sessions?limit=50').catch(() => ({ data: { sessions: [] } })),
      ])
      const chats: ChatSession[] = chatRes.data?.data ?? []
      const debates: DebateSession[] = debateRes.data?.sessions ?? []
      const merged: SessionItem[] = [
        ...chats.map((c) => ({ id: `chat:${c.session_id}`, kind: 'chat' as const, title: c.title || '新对话', updatedAt: c.updated_at, bullish: null, expertCount: 0 })),
        ...debates.map((d) => ({ id: `debate:${d.session_id}`, kind: 'debate' as const, title: d.question || d.scenario || '投研会', updatedAt: d.created_at || d.completed_at || '', bullish: d.probability_assessment, expertCount: d.expert_count })),
      ]
      merged.sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
      setItems(merged)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const handleDelete = async (e: React.MouseEvent, item: SessionItem) => {
    e.stopPropagation()
    if (confirmId !== item.id) { setConfirmId(item.id); return }
    setConfirmId(null)
    try {
      const realId = item.id.split(':')[1]
      const res = item.kind === 'chat'
        ? await apiClient.delete(`/sessions/${realId}`)
        : await apiClient.delete(`/expert-team/sessions/${realId}`)
      if (res.data?.status === 'success' || item.kind === 'debate') setItems((p) => p.filter((x) => x.id !== item.id))
    } catch { /* ignore */ }
  }

  const exportMarkdown = () => {
    const active = items.find((x) => x.id === activeId)
    if (!active) return
    const md = [
      `# ${active.title}`, ``,
      `- 类型：${active.kind === 'debate' ? '投研会' : '对话'}`,
      `- 时间：${active.updatedAt || ''}`,
      active.kind === 'debate' && active.bullish != null ? `- 看涨概率：${active.bullish}%` : '',
      ``,
      `> 由投研工作台导出`,
    ].filter(Boolean).join('\n')
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${active.title.slice(0, 30) || 'session'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const filtered = useMemo(() => items.filter((x) => x.title.toLowerCase().includes(query.toLowerCase())), [items, query])
  const grouped = useMemo(() => {
    const g: Record<GroupKey, SessionItem[]> = { today: [], week: [], older: [] }
    for (const it of filtered) g[groupOf(it.updatedAt)].push(it)
    return g
  }, [filtered])

  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-border/30 bg-card/60">
      <div className="grid grid-cols-1 gap-1.5 border-b border-border/30 p-2">
        <button type="button" onClick={onNewChat} className="flex items-center justify-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 py-1.5 text-[11px] font-medium text-sky-400 hover:bg-sky-500/20 transition-colors">
          <Plus className="h-3.5 w-3.5" /> 新对话
        </button>
        <button type="button" onClick={() => navigate('/research-team')} className="flex items-center justify-center gap-1.5 rounded-lg border py-1.5 text-[11px] font-medium transition-colors hover:opacity-90" style={{ borderColor: 'rgba(167,139,250,0.35)', backgroundColor: 'rgba(167,139,250,0.12)', color: '#A78BFA' }}>
          <Scale className="h-3.5 w-3.5" /> 发起投研会
        </button>
      </div>

      <div className="border-b border-border/20 p-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索会话..." className="w-full rounded-md border border-border/40 bg-secondary/30 py-1 pl-6 pr-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:border-sky-500/50 focus:outline-none" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 custom-scrollbar">
        {isLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-4 w-4 animate-spin text-sky-400/60" /></div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-8 text-center text-[10px] text-muted-foreground">
            <Inbox className="h-4 w-4 opacity-50" />
            <span>{query ? '无匹配结果' : '暂无会话'}</span>
          </div>
        ) : (
          (Object.keys(GROUP_META) as GroupKey[]).map((gk) => {
            const list = grouped[gk]
            if (!list.length) return null
            return (
              <div key={gk} className="mb-2">
                <div className="px-1 pb-1 text-[9px] font-bold uppercase tracking-widest text-muted-foreground/70">{GROUP_META[gk]}</div>
                <div className="space-y-1">
                  {list.map((it) => (
                    <SessionRow key={it.id} item={it} active={activeId === it.id} confirming={confirmId === it.id} onSelect={() => onSelect(it)} onDelete={(e) => handleDelete(e, it)} />
                  ))}
                </div>
              </div>
            )
          })
        )}
      </div>

      <div className="border-t border-border/30 p-2">
        <button type="button" onClick={exportMarkdown} disabled={!activeId} className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-border/40 py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 transition-colors" title={activeId ? '导出当前会话为 Markdown' : '请先选择一个会话'}>
          <Download className="h-3 w-3" /> 导出 Markdown
        </button>
      </div>
    </aside>
  )
}

function SessionRow({ item, active, confirming, onSelect, onDelete }: {
  item: SessionItem
  active: boolean
  confirming: boolean
  onSelect: () => void
  onDelete: (e: React.MouseEvent) => void
}) {
  const badge = item.kind === 'debate' ? debateBadge(item.bullish) : null
  return (
    <div
      onClick={onSelect}
      className={cn(
        'group relative cursor-pointer rounded-md border px-2 py-1.5 transition-all',
        active ? 'border-sky-500/40 bg-sky-500/10' : 'border-transparent hover:border-border/40 hover:bg-secondary/40',
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="shrink-0 text-[11px]">{item.kind === 'debate' ? '⚖️' : '💬'}</span>
        <span className={cn('min-w-0 flex-1 truncate text-[11px]', active ? 'text-sky-300' : 'text-foreground/90')} title={item.title}>{item.title}</span>
        <span className="shrink-0 text-[9px] font-mono text-muted-foreground">{fmtTime(item.updatedAt)}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 pl-4">
        {badge && <span className={cn('rounded-full border px-1.5 py-px text-[8px] font-semibold', badge.cls)}>{badge.label}</span>}
        {item.kind === 'debate' && item.expertCount > 0 && (
          <span className="text-[8px] font-mono text-muted-foreground">{item.expertCount} 位专家</span>
        )}
      </div>
      <button
        type="button"
        onClick={onDelete}
        className={cn(
          'absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 transition-all',
          confirming
            ? 'bg-red-500/20 text-red-400'
            : 'opacity-0 group-hover:opacity-100 text-muted-foreground hover:bg-red-500/15 hover:text-red-400',
        )}
        title={confirming ? '再次点击确认删除' : '删除'}
      >
        {confirming ? <span className="text-[9px] font-bold">确认?</span> : <Trash2 className="h-3 w-3" />}
      </button>
    </div>
  )
}
