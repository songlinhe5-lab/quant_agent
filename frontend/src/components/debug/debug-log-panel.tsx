/**
 * FE-DEBUG-01 底部 DEBUG 面板 — 实时查看主服务 + 各数据子服务日志
 * - 布局：固定底部条带，左右多栏（主服务 + 每节点一栏），高度可拖，上限 1/3 屏
 * - 数据：useDebugLogStream 每 2s 增量轮询 /logs/stream/summary
 * - 控制：折叠 / 暂停 / 清空 / 级别过滤（全局）
 */
import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Pause, Play, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDebugLogStream, type LogEntry } from '@/features/debug/use-debug-log-stream'

const LEVEL_ORDER = ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR'] as const
type Level = (typeof LEVEL_ORDER)[number]

const LEVEL_CLASS: Record<string, string> = {
  DEBUG: 'text-slate-500',
  INFO: 'text-sky-500 dark:text-sky-400',
  WARN: 'text-amber-500',
  ERROR: 'text-red-400',
  CRITICAL: 'text-red-400 font-bold',
}

const LEVEL_BADGE: Record<string, string> = {
  DEBUG: 'bg-slate-500/10 text-slate-400',
  INFO: 'bg-sky-500/10 text-sky-400',
  WARN: 'bg-amber-500/10 text-amber-500',
  ERROR: 'bg-red-500/10 text-red-400',
  CRITICAL: 'bg-red-500/15 text-red-400',
}

const MIN_HEIGHT = 96
const DEFAULT_HEIGHT = 200
const STORAGE = { collapsed: 'quant_debug_panel_collapsed', height: 'quant_debug_panel_height' }

function matchLevel(e: LogEntry, level: Level): boolean {
  if (level === 'ALL') return true
  if (level === 'INFO') return e.level !== 'DEBUG' // INFO 档含 INFO/WARN/ERROR
  return e.level === level
}

function LogRows({ entries, level }: { entries: LogEntry[]; level: Level }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const filtered = entries.filter((e) => matchLevel(e, level))

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [filtered.length])

  if (filtered.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[10px] text-muted-foreground/60 font-mono">
        — 暂无日志 —
      </div>
    )
  }
  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-1 py-0.5 font-mono text-[10px] leading-[17px]">
      {filtered.map((e) => (
        <div key={e.id} className="flex gap-2 whitespace-pre-wrap break-all hover:bg-white/5 rounded px-1">
          <span className="shrink-0 text-slate-500 tabular-nums">{e.ts}</span>
          <span className={cn('shrink-0 w-[52px] text-center rounded px-1', LEVEL_BADGE[e.level] ?? 'bg-slate-500/10 text-slate-400')}>
            {e.level}
          </span>
          <span className="shrink-0 max-w-[150px] truncate text-violet-500 dark:text-violet-400">{e.name}</span>
          <span className={cn('flex-1 min-w-0', LEVEL_CLASS[e.level] ?? 'text-slate-300 dark:text-slate-200')}>{e.message}</span>
        </div>
      ))}
    </div>
  )
}

interface LogPaneProps {
  title: string
  subtitle?: string
  state: 'ok' | 'error' | 'empty'
  entries: LogEntry[]
  level: Level
}

function LogPane({ title, subtitle, state, entries, level }: LogPaneProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col border-r border-border/40 last:border-r-0">
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border/40 px-2">
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full shrink-0',
            state === 'ok' ? 'bg-emerald-500' : state === 'error' ? 'bg-red-500' : 'bg-slate-500',
          )}
          aria-hidden
        />
        <span className="truncate text-[10px] font-bold tracking-wide uppercase">{title}</span>
        {subtitle && <span className="truncate text-[9px] text-muted-foreground">{subtitle}</span>}
        <span className="ml-auto text-[9px] text-muted-foreground tabular-nums">{entries.length}</span>
      </div>
      <div className="min-h-0 flex-1">
        {state === 'error' ? (
          <div className="flex h-full items-center justify-center text-[10px] text-red-400/80 font-mono px-2 text-center">
            节点不可达（子服务未注册或离线）
          </div>
        ) : (
          <LogRows entries={entries} level={level} />
        )}
      </div>
    </div>
  )
}

export function DebugLogPanel() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(STORAGE.collapsed) === '1')
  const [height, setHeight] = useState(() => {
    const v = Number(localStorage.getItem(STORAGE.height) || DEFAULT_HEIGHT)
    return Number.isFinite(v) && v >= MIN_HEIGHT ? v : DEFAULT_HEIGHT
  })
  const [paused, setPaused] = useState(false)
  const [level, setLevel] = useState<Level>('ALL')
  const { nodes, mainEntries, nodeEntries, clearAll } = useDebugLogStream(paused)
  const dragging = useRef(false)

  useEffect(() => {
    localStorage.setItem(STORAGE.collapsed, collapsed ? '1' : '0')
  }, [collapsed])
  useEffect(() => {
    localStorage.setItem(STORAGE.height, String(height))
  }, [height])

  // 拖动调整面板高度（上限 1/3 屏）
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const maxH = window.innerHeight / 3
      const next = Math.min(maxH, Math.max(MIN_HEIGHT, window.innerHeight - e.clientY - 28))
      setHeight(next)
    }
    const onUp = () => {
      dragging.current = false
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  if (collapsed) {
    return (
      <div className="hidden md:flex h-7 shrink-0 items-center gap-2 border-t border-border/40 bg-zinc-950/90 px-3 text-[10px] font-mono text-slate-500 cursor-pointer hover:text-slate-300" onClick={() => setCollapsed(false)}>
        <ChevronUp className="h-3 w-3" />
        <span className="font-bold tracking-widest">DEBUG</span>
        <span className="text-slate-600">|</span>
        <span>主服务 + {nodes.length} 节点日志面板（点击展开）</span>
      </div>
    )
  }

  return (
    <div
      className="hidden md:flex shrink-0 flex-col border-t border-border/50 bg-zinc-950/95 overflow-hidden"
      style={{ height: `${height}px` }}
      data-testid="debug-log-panel"
    >
      {/* 拖动把手 */}
      <div
        className="h-1.5 shrink-0 cursor-row-resize bg-transparent hover:bg-primary/30 transition-colors"
        onMouseDown={(e) => {
          dragging.current = true
          e.preventDefault()
        }}
        title="拖动调整高度"
      />
      {/* 工具条 */}
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border/40 px-2">
        <button
          onClick={() => setCollapsed(true)}
          className="flex items-center gap-1 text-[10px] font-bold tracking-widest text-slate-400 hover:text-slate-200"
          title="折叠"
        >
          <ChevronDown className="h-3.5 w-3.5" />
          DEBUG
        </button>
        <span className="text-[9px] text-muted-foreground tabular-nums">
          主服务 + {nodes.length} 节点 · 2s 刷新
        </span>
        <span className="flex items-center gap-1.5 ml-auto text-[9px]">
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as Level)}
            className="h-5 rounded bg-zinc-900 border border-border/50 px-1 text-[10px] text-slate-300 outline-none"
            title="日志级别过滤"
          >
            {LEVEL_ORDER.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <button
            onClick={() => setPaused((p) => !p)}
            className={cn(
              'flex items-center gap-1 rounded px-1.5 py-0.5 border border-border/50',
              paused ? 'text-amber-400' : 'text-slate-300 hover:text-slate-100',
            )}
            title={paused ? '继续滚动' : '暂停'}
          >
            {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
            {paused ? '继续' : '暂停'}
          </button>
          <button
            onClick={clearAll}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 border border-border/50 text-slate-300 hover:text-red-400"
            title="清空缓冲显示"
          >
            <Trash2 className="h-3 w-3" />
            清空
          </button>
        </span>
      </div>
      {/* 左右多栏日志区 */}
      <div className="flex min-h-0 flex-1">
        <LogPane title="主服务" state="ok" entries={mainEntries} level={level} />
        {nodes.length === 0 && (
          <LogPane
            title="数据服务节点"
            subtitle="无已注册节点"
            state="empty"
            entries={[]}
            level={level}
          />
        )}
        {nodes.map((n) => (
          <LogPane
            key={n.url}
            title={n.name}
            subtitle={n.online ? '在线' : '离线'}
            state={n.online ? 'ok' : 'error'}
            entries={nodeEntries[n.url] ?? []}
            level={level}
          />
        ))}
      </div>
    </div>
  )
}
