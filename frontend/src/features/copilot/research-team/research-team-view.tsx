/**
 * RESEARCH-TEAM-06: AI投研团队 整合视图
 * 左：阵容配置（场景/团队/自定义/轮数/命题）+ 历史会话列表
 * 右：流式会话（专家卡片 + 首席报告）或诚实空态
 *
 * COPILOT-05: 历史区从后端 API 获取真实数据，无数据时展示 EmptyState，
 * 禁止用内存数据伪装历史。
 */
'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Play, Crown, History, Inbox, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RosterPanel, type TeamConfig } from './roster-panel'
import { TeamSession } from './team-session'
import { SessionDetailView } from './session-detail-view'
import { fetchSessionHistory, fetchSession, type SessionSummary, type SessionDetail } from './expert-team-client'

export function ResearchTeamView() {
  const [question, setQuestion] = useState('')
  const [customMode, setCustomMode] = useState(false)
  const [config, setConfig] = useState<TeamConfig>({
    scenario: 'financial_research',
    expertIds: [],
    rounds: 2,
  })
  const [runToken, setRunToken] = useState(0)
  const [running, setRunning] = useState(false)

  // COPILOT-05: 真实历史会话列表
  const [history, setHistory] = useState<SessionSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  // 打开的历史会话详情（点击历史记录项加载）
  const [viewingSession, setViewingSession] = useState<SessionDetail | null>(null)
  const [historyDetailLoading, setHistoryDetailLoading] = useState(false)

  const canRun = question.trim().length > 0 && !running

  // 打开历史记录：加载完整辩论记录并显示在右侧
  const openHistory = useCallback(async (sessionId: string) => {
    setHistoryDetailLoading(true)
    const detail = await fetchSession(sessionId)
    setHistoryDetailLoading(false)
    setViewingSession(detail)
  }, [])

  const onRun = () => {
    if (!canRun) return
    setRunToken((t) => t + 1)
  }

  // COPILOT-05: 从后端 API 拉取真实历史
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const sessions = await fetchSessionHistory(20)
      setHistory(sessions)
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  // 辩论完成后刷新历史
  useEffect(() => {
    if (runToken > 0 && !running) {
      loadHistory()
    }
  }, [running, runToken, loadHistory])

  const hasHistory = history.length > 0

  return (
    <div className="flex h-full min-h-0">
      {/* 左：阵容配置 + 历史 */}
      <div className="flex w-[44%] shrink-0 flex-col border-r border-border/40">
        <div className="flex-1 overflow-y-auto p-3">
          <RosterPanel
            question={question}
            onQuestionChange={setQuestion}
            config={config}
            onConfigChange={setConfig}
            customMode={customMode}
            onCustomModeChange={setCustomMode}
          />

          {/* COPILOT-05: 历史会话区 */}
          <div className="mt-3 border-t border-border/30 pt-3">
            <div className="flex items-center gap-1.5 px-1 mb-2">
              <History className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                历史投研会
              </span>
              {historyLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-auto" />}
            </div>

            {hasHistory ? (
              <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto custom-scrollbar">
                {history.map((s) => (
                  <button
                    key={s.session_id}
                    type="button"
                    onClick={() => openHistory(s.session_id)}
                    className="flex items-center gap-2 rounded-lg border border-border/30 bg-secondary/20 px-2.5 py-2 text-[11px] hover:bg-secondary/40 transition-colors cursor-pointer text-left"
                  >
                    <span className={cn(
                      'h-1.5 w-1.5 rounded-full shrink-0',
                      s.status === 'done' ? 'bg-emerald-500' : s.status === 'error' ? 'bg-red-500' : 'bg-amber-500'
                    )} />
                    <span className="truncate flex-1 text-foreground/80" title={s.question}>
                      {s.question}
                    </span>
                    {s.probability_assessment != null && (
                      <span className={cn(
                        'shrink-0 text-[10px] font-mono font-bold',
                        s.probability_assessment >= 60 ? 'text-emerald-500' : s.probability_assessment <= 40 ? 'text-red-500' : 'text-amber-500'
                      )}>
                        {s.probability_assessment}%
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ) : !historyLoading ? (
              /* COPILOT-05: 诚实空态 —— 禁止用内存数据伪装历史 */
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <Inbox className="h-8 w-8 text-muted-foreground/30 mb-2" />
                <p className="text-[11px] text-muted-foreground/60 leading-relaxed max-w-[200px]">
                  暂无投研会记录
                  <br />
                  <span className="text-[10px] text-muted-foreground/40">
                    发起一次投研会后，记录将自动持久化
                  </span>
                </p>
              </div>
            ) : null}
          </div>
        </div>
        <div className="border-t border-border/40 p-2">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun}
            className={cn(
              'flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors',
              canRun
                ? 'bg-scene text-white hover:bg-scene/90'
                : 'cursor-not-allowed bg-white/5 text-muted-foreground',
            )}
          >
            {running ? <Crown className="h-3.5 w-3.5 animate-pulse" /> : <Play className="h-3.5 w-3.5" />}
            {running ? '投研会进行中…' : '发起投研会'}
          </button>
        </div>
      </div>

      {/* 右：历史详情 or 会话流 */}
      <div className="relative min-w-0 flex-1">
        {viewingSession ? (
          <>
            {/* 关闭历史详情，回到会话流 */}
            <button
              type="button"
              onClick={() => setViewingSession(null)}
              className="absolute right-3 top-2 z-10 rounded-full border border-border/40 bg-background/80 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-secondary/40 hover:text-foreground transition-colors"
            >
              {historyDetailLoading ? '加载中…' : '✕ 关闭历史'}
            </button>
            {historyDetailLoading && !viewingSession ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">加载历史记录…</div>
            ) : viewingSession ? (
              <SessionDetailView session={viewingSession} />
            ) : null}
          </>
        ) : (
          <TeamSession
            question={question}
            config={config}
            customMode={customMode}
            runToken={runToken}
            onRunningChange={setRunning}
          />
        )}
      </div>
    </div>
  )
}
