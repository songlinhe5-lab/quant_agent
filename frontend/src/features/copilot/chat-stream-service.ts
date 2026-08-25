import { fetchWithAuth, API_BASE_URL, clearTokens, emitAuthRequired, ApiError } from '@/lib/api-client'

/** SSE 流式解析回调——由 useChat hook 注入，service 不直接依赖 store */
export interface StreamCallbacks {
  onTextChunk: (content: string) => void
  /** COPILOT-03/P0-4: 真实推理片段（Plan 阶段），不再静默丢弃 */
  onReasoningChunk: (content: string) => void
  onThinkEnd: () => void
  onToolStart: (name: string, input: string) => void
  onToolResult: (name: string, result: unknown) => void
  onError: (content: string) => void
  onStrategyCode: (code: string) => void
  onChartAnnotation: (data: any) => void
  /** COPILOT-09: ReAct 迭代上限已达 */
  onIterationLimitReached: (maxIterations: number) => void
  onFlush: () => void
  onStreamEnd: () => void
}

export interface StreamParams {
  sessionId: string
  userContent: string
  signal: AbortSignal
}

/**
 * SSE 流式请求与 NDJSON 解析服务。
 * 纯函数式，不依赖 React / Zustand，仅通过 callbacks 与外部通信。
 */
export async function runChatStream(params: StreamParams, cb: StreamCallbacks): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE_URL}/chat`, {
    method: 'POST',
    body: JSON.stringify({
      messages: [{ role: 'user', content: params.userContent }],
      session_id: params.sessionId,
    }),
    signal: params.signal,
  })

  if (!res.ok) {
    const statusText = res.statusText || 'Unknown'
    let detail = ''
    try {
      const errorBody = await res.text()
      try {
        const errorJson = JSON.parse(errorBody)
        detail = errorJson.detail || errorJson.msg || errorJson.message || errorBody
      } catch {
        detail = errorBody.slice(0, 200)
      }
    } catch {
      detail = '无法读取响应体'
    }
    throw new Error(`HTTP ${res.status} (${statusText}): ${detail}`)
  }

  if (!res.body) throw new Error('网络响应异常 (No Body)')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let lastUpdateTime = Date.now()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.trim()) continue
      try {
        const data = JSON.parse(line)

        if (data.type === 'text_chunk') {
          cb.onTextChunk(data.content)
          if (data.content?.includes('</think>')) cb.onThinkEnd()
        } else if (data.type === 'reasoning_chunk') {
          // 后端 hermes_agent 在思考阶段推送的真实推理流；计入 flush 节流
          cb.onReasoningChunk(data.content)
        } else if (data.type === 'tool_start') {
          cb.onToolStart(data.name, data.input)
        } else if (data.type === 'tool_result') {
          cb.onToolResult(data.name, data.result)
        } else if (data.type === 'error') {
          cb.onError(data.content)
        } else if (data.type === 'strategy_code') {
          cb.onStrategyCode(data.code)
        } else if (data.type === 'chart_annotation') {
          cb.onChartAnnotation(data.data)
        } else if (data.type === 'iteration_limit_reached') {
          cb.onIterationLimitReached(data.max_iterations ?? 8)
        }

        const now = Date.now()
        const isToolEvent = ['tool_start', 'tool_result', 'error', 'strategy_code', 'chart_annotation'].includes(data.type)
        if (isToolEvent || now - lastUpdateTime > 50) {
          cb.onFlush()
          lastUpdateTime = now
        }
      } catch {
        // 忽略非法 JSON 切片
      }
    }
  }

  cb.onFlush()
  cb.onStreamEnd()
}

/** 统一错误分类，返回应追加到消息尾部的人类可读提示 */
export function classifyChatError(error: any): { message: string; isAuth: boolean } {
  if (error?.name === 'AbortError') {
    return { message: '\n\n> 🛑 **思考已中断**: 用户主动终止了当前的推演。', isAuth: false }
  }
  if (error instanceof ApiError && error.code === 401) {
    return { message: '\n\n> ❌ **登录态已失效**: 会话令牌已过期或被吊销，正在为你跳转登录页重新授权…', isAuth: true }
  }
  const errMsg = error?.message || String(error)
  if (errMsg.includes('Failed to fetch') || errMsg.includes('NetworkError') || errMsg.includes('fetch')) {
    return { message: `\n\n> ❌ **网络连接失败**: 无法连接到后端服务，请检查后端是否正在运行。\n> \n> 技术详情: \`${errMsg}\``, isAuth: false }
  }
  if (errMsg.includes('HTTP')) {
    return { message: `\n\n> ❌ **后端响应异常**: ${errMsg}`, isAuth: false }
  }
  if (errMsg.includes('stream') || errMsg.includes('reader') || errMsg.includes('decode')) {
    return { message: `\n\n> ❌ **数据流中断**: 流式传输过程中连接被意外切断。\n> \n> 技术详情: \`${errMsg}\``, isAuth: false }
  }
  return { message: `\n\n> ❌ **网络/打断异常**: 请求被意外中断。\n> \n> 技术详情: \`${errMsg}\``, isAuth: false }
}
