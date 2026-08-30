'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'
import { useChatStore } from '@/stores/useChatStore'
import { Paperclip, CandlestickChart, Shield, Filter, Star, Wrench, CheckCircle2, Clock, Cpu } from 'lucide-react'

const KIND_ICON: Record<string, React.ReactNode> = {
  screener: <Filter className="h-3 w-3" />,
  kline: <CandlestickChart className="h-3 w-3" />,
  risk: <Shield className="h-3 w-3" />,
  analysis: <Star className="h-3 w-3" />,
}

/** 后端 GET /market/health/services 的单源健康快照 */
interface ServiceHealth {
  name: string
  status: string
  cooldown_remaining?: number
  message?: string
}

/** 非故障态：健康 / 未启用 / 仅告警（如未配置 API Key）都不该显示为熔断 */
const NON_FAULT_STATUS = new Set(['healthy', 'disabled', 'warning'])

/**
 * COPILOT-19: B3 运行信息列（可折叠）
 *  页面上下文(useCopilotContextStore) + 附加开关 + 工具流水 + 运行参数
 */
export function RunInfoPanel({ modelName }: { modelName: string }) {
  const context = useCopilotContextStore((s) => s.context)
  const clearContext = useCopilotContextStore((s) => s.clearContext)
  const messages = useChatStore((s) => s.messages)
  const [attach, setAttach] = useState(false)

  // 本次会话工具流水：从各消息 tools 扁平化
  const toolTrail = useMemo(() => {
    const arr: { name: string; status: string; result?: string }[] = []
    for (const m of messages) {
      if (m.tools?.length) for (const t of m.tools) arr.push({ name: t.name, status: t.status, result: t.result })
    }
    return arr
  }, [messages])

  // 迭代数 = 工具步数
  const iterCount = toolTrail.length

  // RL-14: 熔断状态读后端真实快照，不再用本地连续失败数猜。
  // 此前以工具返回文本是否含 error 计数（>=3 即"已熔断"），与后端熔断器实际状态
  // 无关——上游已恢复仍显示熔断、熔断中却不显示，属误导性猜测。
  const [unhealthy, setUnhealthy] = useState<ServiceHealth[]>([])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const res = await apiClient.get('/market/health/services')
        const list: ServiceHealth[] = Array.isArray(res?.data) ? res.data : []
        if (!alive) return
        setUnhealthy(list.filter((s) => !NON_FAULT_STATUS.has(s.status)))
      } catch {
        // 探测接口本身不可用时保持静默，不猜测
        if (alive) setUnhealthy([])
      }
    }
    void load()
    const timer = window.setInterval(load, 15000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  // 冷却剩余：后端熔断器给出的真实恢复倒计时（0 表示无冷却信息）
  const maxCooldown = useMemo(
    () => unhealthy.reduce((m, s) => Math.max(m, s.cooldown_remaining ?? 0), 0),
    [unhealthy],
  )

  return (
    <div className="flex h-full flex-col">
      {/* 页面上下文 */}
      <div className="border-b border-border/20 p-3">
        <div className="mb-1.5 flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest text-muted-foreground">
          <Paperclip className="h-3 w-3" /> 页面上下文
        </div>
        {context ? (
          <div className="rounded-lg border border-scene/30 bg-scene/10 p-2">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold text-scene">
              {KIND_ICON[context.kind] ?? null}
              <span className="truncate">{context.title}</span>
            </div>
            <p className="mt-1 line-clamp-3 text-[9px] leading-relaxed text-scene/80">{context.summary}</p>
            <div className="mt-1.5 flex items-center gap-2">
              <label className="flex cursor-pointer items-center gap-1 text-[9px] text-muted-foreground">
                <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} className="h-2.5 w-2.5 accent-scene" />
                附加到下一条消息
              </label>
              <button type="button" onClick={clearContext} className="ml-auto text-[9px] text-muted-foreground hover:text-red-400">移除</button>
            </div>
          </div>
        ) : (
          <p className="rounded-lg border border-border/30 bg-secondary/10 p-2 text-[9px] text-muted-foreground">
            暂无页面上下文。在选股器 / K线 / 风控页聚焦后自动注入。
          </p>
        )}
      </div>

      {/* 工具调用记录 */}
      <div className="flex-1 min-h-0 overflow-y-auto border-b border-border/20 p-3 custom-scrollbar">
        <div className="mb-1.5 flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest text-muted-foreground">
          <Wrench className="h-3 w-3" /> 工具调用记录
        </div>
        {toolTrail.length === 0 ? (
          <p className="text-[9px] text-muted-foreground/70">本次会话暂无工具调用</p>
        ) : (
          <div className="space-y-1">
            {toolTrail.map((t, i) => (
              <div key={i} className="flex items-center gap-1.5 rounded-md border border-border/20 bg-secondary/10 px-2 py-1">
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', t.status === 'done' ? (t.result && /error|failed/i.test(t.result) ? 'bg-red-400' : 'bg-emerald-400') : 'bg-amber-400 animate-pulse')} />
                <span className="min-w-0 flex-1 truncate font-mono text-[9px] text-foreground/80">{t.name}</span>
                {t.status === 'done' && <CheckCircle2 className="h-2.5 w-2.5 shrink-0 text-emerald-400" />}
              </div>
            ))}
          </div>
        )}
        {unhealthy.length > 0 && (
          <div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 p-1.5 text-center text-[9px] font-semibold text-red-400">
            ⛔ {unhealthy.map((s) => s.name).join('、')} 不可用
            {maxCooldown > 0 ? ` · ${Math.ceil(maxCooldown)}s 后恢复` : ' · 检查数据源'}
          </div>
        )}
      </div>

      {/* 运行参数 */}
      <div className="p-3">
        <div className="mb-1.5 flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest text-muted-foreground">
          <Cpu className="h-3 w-3" /> 运行参数
        </div>
        <div className="space-y-1.5 text-[9px] text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>模型</span>
            <span className="font-mono text-foreground/80">{modelName || '—'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>迭代</span>
            <span className="font-mono text-foreground/80">第 {iterCount}/8 步</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1"><Clock className="h-2.5 w-2.5" /> 会话 TTL</span>
            <span className="font-mono text-foreground/80">热 12h</span>
          </div>
        </div>
      </div>
    </div>
  )
}
