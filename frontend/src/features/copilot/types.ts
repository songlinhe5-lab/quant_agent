export interface ToolStep {
  id?: string
  name: string
  input: string
  result?: string
  status: 'running' | 'done'
}

export interface ChatAttachment {
  name: string
  url: string
  type: string
}

export interface StrategyBlock {
  code: string
}

/** PROD-02: AI 输出的 K 线内联标注协议（图表可机器读取） */
export type SignalSide = 'buy' | 'sell'

export interface SignalAnnotation {
  /** 触发时间：'YYYY-MM-DD' 或 Unix 秒（UTCTimestamp） */
  time: string | number
  side: SignalSide
  price?: number
  label?: string
}

export type LevelType = 'support' | 'resistance' | 'target' | 'stop'

export interface LevelAnnotation {
  price: number
  type: LevelType
  label?: string
}

export interface ZoneAnnotation {
  lower: number
  upper: number
  label?: string
  /** 可选 RGBA，默认紫色半透明 */
  color?: string
}

export interface ChartAnnotationPayload {
  /** 标注所属标的（如 AAPL / US.AAPL / 00700.HK） */
  symbol: string
  signals?: SignalAnnotation[]
  levels?: LevelAnnotation[]
  zones?: ZoneAnnotation[]
  note?: string
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  tools?: ToolStep[]
  startTime?: number
  thinkEndTime?: number
  attachments?: ChatAttachment[]
  strategyBlocks?: StrategyBlock[]
  /** PROD-02: 本消息携带的图表标注 */
  chartAnnotations?: ChartAnnotationPayload[]
  /** COPILOT-09: ReAct 迭代上限已达，后续内容为降级兜底总结 */
  iterationLimitReached?: boolean
}
