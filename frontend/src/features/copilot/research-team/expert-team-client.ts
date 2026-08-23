/**
 * RESEARCH-TEAM-02: 专家团 SSE 客户端
 * 对接 backend/routers/expert_team.py 的 POST /api/v1/expert-team/analyze
 * SSE 文本格式: "data: {json}\n\n"，payload.type 区分事件类型。
 * 解析 StreamEvent 协议（见 backend/services/expert_team/event_schema）。
 * COPILOT-08: 从 apiClient.stream 改走 fetchWithAuth，对齐 chat-stream-service 口径（带 401 自动续期重试）。
 */
import { apiClient, fetchWithAuth, API_BASE_URL, ApiError } from '@/lib/api-client'

export type StreamEventType =
  | 'status'
  | 'data_collect'
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

/** 数据采集过程：后端逐项透传（供折叠思考过程展示） */
export interface DataCollectEvent extends BaseEvent {
  type: 'data_collect'
  message: string
  data?: {
    key?: string
    status?: 'success' | 'error' | 'timeout' | 'skipped' | string
    message?: string
  }
}

/** 专家结构化观点判断（后端 ExpertOpinion.model_dump()，随首片 expert_opinion 事件经 data 透传） */
export interface ExpertOpinionData {
  expert_id: string
  round: number
  /** 核心观点 (<=200字) */
  stance: string
  /** 置信度 0-100 */
  confidence: number
  /** 关键依据 */
  key_evidence?: string[]
  /** 完整推理过程 */
  reasoning?: string
  /** Round2: 对其他专家的质疑 */
  challenges?: string[]
  /** Round2: 置信度变化 */
  confidence_delta?: number
  /** Round2: 修正后观点 */
  revised_stance?: string
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
  /** 结构化观点判断：后端仅首片附带（model_dump），前端据此渲染 stance/confidence */
  data?: ExpertOpinionData
}

export interface RoundCompleteEvent extends BaseEvent {
  type: 'round_complete'
  round: number
  message?: string
}

export interface ChiefReportData {
  consensus_areas?: string[]
  divergence_areas?: string[]
  strongest_bull_case?: string
  strongest_bear_case?: string
  probability_assessment?: number
  final_recommendation?: string
  risk_warnings?: string[]
  minority_opinion?: string
  full_report?: string
}

export interface ChiefReportEvent extends BaseEvent {
  type: 'chief_report'
  /** 首席最终报告 Markdown */
  content: string
  /** 结构化字段（如有）：概率/结论/矩阵，由后端 JSON 字段透传 */
  bullish_probability?: number
  conclusion?: string
  /** COPILOT-17: 后端 ChiefReport.model_dump() 结构化字段 */
  data?: ChiefReportData
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
  | DataCollectEvent
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
 * COPILOT-08: 发起专家团分析，fetchWithAuth + ReadableStream 解析 SSE。
 * 对齐 chat-stream-service 口径，带 401 自动续期重试。
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

  fetchWithAuth(`${API_BASE_URL}/expert-team/analyze`, {
    method: 'POST',
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }
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

// ─── COPILOT-05: 会话历史 API ───────────────────────────────────

export interface SessionSummary {
  session_id: string
  scenario: string
  question: string
  status: string
  expert_count: number
  probability_assessment: number | null
  created_at: string
  completed_at: string
}

/** 获取投研会历史会话列表 */
export async function fetchSessionHistory(limit = 20): Promise<SessionSummary[]> {
  const res = await apiClient.get(`/expert-team/sessions?limit=${limit}`)
  if (res.data?.sessions) return res.data.sessions
  return []
}

/** 获取单个投研会完整辩论记录 */
export async function fetchSession(sessionId: string): Promise<Record<string, unknown> | null> {
  try {
    const res = await apiClient.get(`/expert-team/sessions/${sessionId}`)
    return res.data ?? null
  } catch {
    return null
  }
}
