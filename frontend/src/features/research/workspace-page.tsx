'use client'

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Microscope, PanelRightClose, PanelRightOpen, Activity, Archive, Minimize2 } from 'lucide-react'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { MODE_META } from '@/features/trading/trading-mode-types'
import { SessionCenter, type SessionItem } from './session-center'
import { ChatWorkspace } from './chat-workspace'
import { DebateComposer, type ComposerResult } from './debate-composer'
import { DebateRoom } from './debate-room'
import { AssetLibrary } from './asset-library'
import { RunInfoPanel } from './run-info-panel'
import { useChatStore } from '@/stores/useChatStore'
import type { TeamConfig } from '@/features/copilot/research-team/roster-panel'

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
type B2Mode = 'chat' | 'composer' | 'debate' | 'assets'

export function ResearchWorkspacePage() {
  const [meta, setMeta] = useState<ResearchMeta>({ tools_count: 0, model_name: '' })
  const [b3Open, setB3Open] = useState(true)
  const [activeSession, setActiveSession] = useState<SessionItem | undefined>(undefined)
  // B2 主区模式：对话 / 组局态(COPILOT-15) / 辩论态(COPILOT-16)
  const [b2Mode, setB2Mode] = useState<B2Mode>('chat')
  const [debateRun, setDebateRun] = useState<{ question: string; config: TeamConfig; runToken: number } | null>(null)
  const chatMessages = useChatStore((s) => s.messages)
  // COPILOT-19: 折叠后关键状态（迭代数）微徽章
  const chatIterCount = chatMessages.reduce((acc, m) => acc + (m.tools?.length ?? 0), 0)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const openCopilot = useLayoutStore((s) => s.openCopilot)
  const handleSelectSession = useChatStore((s) => s.handleSelectSession)
  const mode = useTradingModeStore((s) => s.mode)
  const modeMeta = MODE_META[mode]

  // COPILOT-20: 反向「收起」→ 打开抽屉返回
  const collapseToDrawer = () => {
    openCopilot()
    navigate('/')
  }

  const handleLaunchDebate = (r: ComposerResult) => {
    // runToken>0 才触发 TeamSession 的 run()；每次发起递增避免重复 key remount
    setDebateRun((prev) => ({
      question: r.question,
      config: { scenario: r.scenario, expertIds: r.expertIds, rounds: r.rounds },
      runToken: (prev?.runToken ?? 0) + 1,
    }))
    setB2Mode('debate')
  }

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

  // COPILOT-20: 从抽屉展开进入时，加载 ?session= 指定的会话到共享 useChatStore
  useEffect(() => {
    const sid = searchParams.get('session')
    if (sid && handleSelectSession) {
      handleSelectSession(sid).catch(() => { /* 会话不存在则保持当前状态 */ })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  return (
    <div className="h-[calc(100vh-100px)] w-full overflow-hidden rounded-xl border border-border/40 bg-card flex flex-col">
      {/* 页面标题条 */}
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border/30 px-4">
        <Microscope className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-semibold tracking-wide text-foreground">投研</h1>
        <span className="text-[10px] text-muted-foreground font-mono truncate">
          Hermes ReAct · {meta.tools_count} tools · {meta.model_name}
        </span>
        <button
          type="button"
          onClick={() => setB2Mode('assets')}
          className={cn(
            'ml-2 flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors',
            b2Mode === 'assets'
              ? 'border-sky-500/40 bg-sky-500/10 text-sky-400'
              : 'border-border/40 text-muted-foreground hover:bg-secondary/50 hover:text-foreground',
          )}
          title="资产库"
        >
          <Archive className="h-3 w-3" /> 资产库
        </button>
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
        {/* COPILOT-20: 收起 → 返回抽屉形态 */}
        <button
          type="button"
          onClick={collapseToDrawer}
          className="flex items-center gap-1 rounded-full border border-border/40 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition-colors"
          title="收起为抽屉形态"
        >
          <Minimize2 className="h-3 w-3" /> 收起
        </button>
      </div>

      {/* 三列骨架 */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* B1 会话中心（COPILOT-13） */}
        <SessionCenter
          activeId={activeSession?.id}
          onSelect={(it) => { setActiveSession(it); if (it.kind === 'debate') setB2Mode('chat') }}
          onNewChat={() => { setActiveSession(undefined); setB2Mode('chat') }}
          onNewDebate={() => { setActiveSession(undefined); setB2Mode('composer') }}
        />

        {/* B2 主区：对话(COPILOT-14) / 组局态(COPILOT-15) / 辩论态(COPILOT-16) / 资产库(COPILOT-18) */}
        <main className="relative flex-1 min-w-0 flex flex-col">
          {b2Mode === 'assets' ? (
            <AssetLibrary onClose={() => setB2Mode('chat')} />
          ) : b2Mode === 'composer' ? (
            <DebateComposer
              onLaunch={handleLaunchDebate}
              onUseHoldings={() => { /* 预留：资产库接入后从当前持仓生成命题 */ }}
            />
          ) : b2Mode === 'debate' && debateRun ? (
            <DebateRoom
              key={debateRun.runToken}
              question={debateRun.question}
              config={debateRun.config}
              runToken={debateRun.runToken}
              // COPILOT-17: 调整阵容重跑 → 回填组局态；追问首席 → 切对话模式
              onRerun={() => setB2Mode('composer')}
              onAskChief={() => { setActiveSession(undefined); setB2Mode('chat') }}
            />
          ) : (
            <ChatWorkspace />
          )}
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
            <div className="min-h-0 flex-1 overflow-hidden">
              <RunInfoPanel modelName={meta.model_name} />
            </div>
          </aside>
        )}

        {/* 折叠后的展开按钮 + 迭代/熔断微徽章 */}
        {!b3Open && (
          <div className="flex shrink-0 flex-col items-center self-center gap-1 border-l border-border/30 py-1">
            <button
              type="button"
              onClick={() => setB3Open(true)}
              className="border border-border/30 border-l-0 rounded-r-md bg-secondary/30 p-1 text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
              aria-label="展开运行信息列"
              title="展开"
            >
              <PanelRightOpen className="h-3.5 w-3.5" />
            </button>
            {/* 折叠后关键状态微徽章 */}
            <span className="rounded-full border border-border/40 bg-secondary/20 px-1.5 text-[8px] font-mono text-muted-foreground" title="迭代步数">
              {chatIterCount}/8
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
