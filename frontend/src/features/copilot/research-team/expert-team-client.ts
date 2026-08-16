/**
 * RESEARCH-TEAM-02: 专家团 SSE 客户端
 * 对接 backend/routers/expert_team.py 的 POST /api/v1/expert-team/analyze
 * SSE 文本格式: "data: {json}\n\n"，payload.type 区分事件类型。
 * 解析 StreamEvent 协议（见 backend/services/expert_team/event_schema）。
 * 使用 apiClient.stream（裸 fetch，返回原始 Response，不 .json() 避免缓冲整流）。
 */
import { apiClient } from '@/lib/api-client'
import type { ApiError } from '@/lib/api-client'

export type StreamEventType =
  | 'status'
  | 'expert_opinion'
  | 'round_complete'
  | 'chief_report'
  | 'error'
  | 'done'

export interface BaseEvent {
  type: StreamEventType
}

export interface StatusEvent extends BaseEvent {
  type: 'status'
  message: string
}

export interface ExpertOpinionEvent extends BaseEvent {
  type: 'expert_opinion'
  expert_id: string
  expert_name?: string
  round: number
  /** 流式增量文本（逐 token 追加到对应专家卡片） */
  content: string
  /** round_complete 时可能带完整文本 */
  full_text?: string
}

export interface RoundCompleteEvent extends BaseEvent {
  type: 'round_complete'
  round: number
  message?: string
}

export interface ChiefReportEvent extends BaseEvent {
  type: 'chief_report'
  /** 首席最终报告 Markdown */
  content: string
  /** 结构化字段（如有）：概率/结论/矩阵，由后端 JSON 字段透传 */
  bullish_probability?: number
  conclusion?: string
}

export interface ErrorEvent extends BaseEvent {
  type: 'error'
  message: string
}

export interface DoneEvent extends BaseEvent {
  type: 'done'
  session_id?: string
}

export type TeamStreamEvent =
  | StatusEvent
  | ExpertOpinionEvent
  | RoundCompleteEvent
  | ChiefReportEvent
  | ErrorEvent
  | DoneEvent

export interface AnalyzeParams {
  question: string
  scenario?: string
  ticker?: string
  /** 自定义专家组合（覆盖场景默认阵容） */
  expert_ids?: string[]
  rounds?: number
  code_context?: string
}

export interface TeamStreamHandlers {
  onEvent: (e: TeamStreamEvent) => void
  onError?: (err: Error) => void
}

/**
 * 发起专家团分析，原生 fetch + ReadableStream 解析 SSE。
 * 返回 AbortController，调用方可在组件卸载/用户中止时 abort。
 */
export function startTeamAnalysis(params: AnalyzeParams, handlers: TeamStreamHandlers): AbortController {
  const controller = new AbortController()

  const body: Record<string, unknown> = {
    question: params.question,
    scenario: params.scenario ?? 'financial_research',
    rounds: params.rounds ?? 2,
  }
  if (params.ticker) body.ticker = params.ticker
  if (params.expert_ids && params.expert_ids.length > 0) body.expert_ids = params.expert_ids
  if (params.code_context) body.code_context = params.code_context

  apiClient
    .stream('/expert-team/analyze', body, controller.signal)
    .then((res) => {
      if (!res.body) throw new Error('响应无流主体')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const pump = (): Promise<void> =>
        reader.read().then(({ done, value }) => {
          if (done) return
          buffer += decoder.decode(value, { stream: true })
          // SSE 以 \n\n 分隔事件块
          const chunks = buffer.split('\n\n')
          buffer = chunks.pop() ?? ''
          for (const chunk of chunks) {
            const line = chunk.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            const payload = line.slice(5).trim()
            if (!payload) continue
            try {
              const evt = JSON.parse(payload) as TeamStreamEvent
              handlers.onEvent(evt)
            } catch {
              /* 忽略无法解析的落单帧 */
            }
          }
          return pump()
        })

      return pump()
    })
    .catch((err: unknown) => {
      if (controller.signal.aborted) return
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : '分析启动失败'
      handlers.onError?.(new Error(msg))
    })

  return controller
}
