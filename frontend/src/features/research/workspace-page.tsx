'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Microscope, PanelRightClose, PanelRightOpen, Activity } from 'lucide-react'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { MODE_META } from '@/features/trading/trading-mode-types'
import { SessionCenter, type SessionItem } from './session-center'

interface ResearchMeta {
  tools_count: number
  model_name: string
}

/**
 * COPILOT-12: 投研工作台 · 三列骨架
 *  - B1 会话中心(240px) / B2 主区(1fr) / B3 运行信息(280px, 可折叠)
 *  - 标题条副标题 Hermes ReAct · {tools_count} tools · {model_name}（来自 GET /research/meta，禁止写死）
 *  - 右侧 SANDBOX/LIVE 徽章（与策略工作台同口径）
 */
export function ResearchWorkspacePage() {
  const [meta, setMeta] = useState<ResearchMeta>({ tools_count: 0, model_name: '' })
  const [b3Open, setB3Open] = useState(true)
  const [activeSession, setActiveSession] = useState<SessionItem | undefined>(undefined)
  const mode = useTradingModeStore((s) => s.mode)
  const modeMeta = MODE_META[mode]

  useEffect(() => {
    let mounted = true
    apiClient
      .get('/research/meta')
      .then((res: any) => {
        if (mounted && res?.data?.status === 'success') {
          setMeta({
            tools_count: res.data.data?.tools_count ?? 0,
            model_name: res.data.data?.model_name ?? '',
          })
        }
      })
      .catch(() => { /* 忽略：骨架可降级为空副标题 */ })
    return () => { mounted = false }
  }, [])

  return (
    <div className="h-[calc(100vh-100px)] w-full overflow-hidden rounded-xl border border-border/40 bg-card flex flex-col">
      {/* 页面标题条 */}
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border/30 px-4">
        <Microscope className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-semibold tracking-wide text-foreground">投研</h1>
        <span className="text-[10px] text-muted-foreground font-mono truncate">
          Hermes ReAct · {meta.tools_count} tools · {meta.model_name}
        </span>
        {/* SANDBOX/LIVE 徽章（与策略工作台同口径） */}
        <span
          className={cn(
            'ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            mode === 'LIVE'
              ? 'bg-red-500/15 text-red-400 border border-red-500/30'
              : mode === 'PAPER'
                ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
          )}
          title={modeMeta?.hint}
        >
          {modeMeta?.emoji} {modeMeta?.label}
        </span>
      </div>

      {/* 三列骨架 */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* B1 会话中心（COPILOT-13） */}
        <SessionCenter
          activeId={activeSession?.id}
          onSelect={(it) => setActiveSession(it)}
          onNewChat={() => setActiveSession(undefined)}
          onNewDebate={() => setActiveSession(undefined)}
        />

        {/* B2 主区 */}
        <main className="flex-1 min-w-0 flex flex-col">
          <div className="flex-1 flex items-center justify-center p-6 text-center text-[10px] text-muted-foreground">
            {activeSession
              ? `已选中：${activeSession.title}（${activeSession.kind === 'debate' ? '投研会' : '对话'}）— B2 主区 COPILOT-14~17 填充`
              : '对话 / 辩论室主区骨架（COPILOT-14~17 填充）'}
          </div>
        </main>

        {/* B3 运行信息（可折叠） */}
        {b3Open && (
          <aside className="w-[280px] shrink-0 border-l border-border/30 flex flex-col">
            <div className="flex h-8 items-center gap-2 px-3 border-b border-border/20">
              <Activity className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">运行信息</span>
              <button
                type="button"
                onClick={() => setB3Open(false)}
                className="ml-auto p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
                aria-label="折叠运行信息列"
                title="折叠"
              >
                <PanelRightClose className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="flex-1 flex items-center justify-center p-4 text-center text-[10px] text-muted-foreground">
              工具调用轨迹 / 状态骨架（COPILOT-19 填充）
            </div>
          </aside>
        )}

        {/* 折叠后的展开按钮 */}
        {!b3Open && (
          <button
            type="button"
            onClick={() => setB3Open(true)}
            className="shrink-0 self-center border border-border/30 border-l-0 rounded-r-md bg-secondary/30 p-1 text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
            aria-label="展开运行信息列"
            title="展开"
          >
            <PanelRightOpen className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
