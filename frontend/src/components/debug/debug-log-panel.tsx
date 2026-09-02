/**
 * FE-DEBUG-01 底部 DEBUG 面板 — 实时查看主服务 + 各数据子服务日志
 * - 布局：固定底部条带，Tab 切换（主服务 + 每节点一个页签），单栏全宽展示，高度可拖，上限 2/3 屏
 * - 数据：useDebugLogStream 每 2s 增量轮询 /logs/stream/summary（后台各节点缓冲不中断，切 Tab 即时可见）
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
const DEFAULT_HEIGHT = 240
const MAX_HEIGHT_RATIO = 2 / 3 // 可拖到 2/3 屏，看长日志不用受罪
const STORAGE = { collapsed: 'quant_debug_panel_collapsed', height: 'quant_debug_panel_height', tab: 'quant_debug_panel_tab' }

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

// ── 单个日志页签内容（全宽；节点不可达由 Tab 区处理） ──────────────

function LogPane({ entries, level }: { entries: LogEntry[]; level: Level }) {
  return (
    <div className="h-full min-w-0">
      <LogRows entries={entries} level={level} />
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
  const [activeTab, setActiveTab] = useState<string>(() => localStorage.getItem(STORAGE.tab) || 'main')
  const { nodes, mainEntries, nodeEntries, clearAll } = useDebugLogStream(paused)
  const dragging = useRef(false)

  useEffect(() => {
    localStorage.setItem(STORAGE.collapsed, collapsed ? '1' : '0')
  }, [collapsed])
  useEffect(() => {
    localStorage.setItem(STORAGE.height, String(height))
  }, [height])
  useEffect(() => {
    localStorage.setItem(STORAGE.tab, activeTab)
  }, [activeTab])

  // 拖动调整面板高度（上限 2/3 屏）
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const maxH = window.innerHeight * MAX_HEIGHT_RATIO
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
      {/* Tab 页签（主服务 + 各节点）+ 单栏全宽日志区 */}
      {(() => {
        const tabs = [
          { id: 'main', name: '主服务', subtitle: undefined, state: 'ok' as const, entries: mainEntries },
          ...nodes.map((n) => ({
            id: n.url,
            name: n.name,
            subtitle: n.online ? '在线' : '离线',
            state: (n.online ? 'ok' : 'error') as 'ok' | 'error',
            entries: nodeEntries[n.url] ?? [],
          })),
        ]
        const active = tabs.find((t) => t.id === activeTab) ?? tabs[0]
        return (
          <>
            <div className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-border/40 bg-zinc-950/60" data-testid="debug-log-tabs">
              {tabs.map((t) => {
                const isActive = t.id === active.id
                const count = t.entries.length
                return (
                  <button
                    key={t.id}
                    onClick={() => setActiveTab(t.id)}
                    className={cn(
                      'flex shrink-0 items-center gap-1.5 border-b-2 px-3 text-[10px] font-bold tracking-wide uppercase transition-colors',
                      isActive
                        ? 'border-primary text-foreground'
                        : 'border-transparent text-slate-500 hover:text-slate-300',
                    )}
                  >
                    <span
                      className={cn(
                        'h-1.5 w-1.5 rounded-full shrink-0',
                        t.state === 'ok' ? 'bg-emerald-500' : t.state === 'error' ? 'bg-red-500' : 'bg-slate-500',
                      )}
                      aria-hidden
                    />
                    {t.name}
                    <span className={cn('tabular-nums font-normal', count > 0 ? 'text-slate-500' : 'text-slate-700')}>{count}</span>
                  </button>
                )
              })}
            </div>
            <div className="min-h-0 flex-1">
              {active.state === 'error' ? (
                <div className="flex h-full items-center justify-center text-[10px] text-red-400/80 font-mono px-2 text-center">
                  {active.name} 节点不可达（子服务未注册或离线）
                </div>
              ) : (
                <LogPane entries={active.entries} level={level} />
              )}
            </div>
          </>
        )
      })()}
    </div>
  )
}
