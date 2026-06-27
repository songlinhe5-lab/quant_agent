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

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  tools?: ToolStep[]
  startTime?: number
  thinkEndTime?: number
  attachments?: ChatAttachment[]
}