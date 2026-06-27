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

export interface ChatState {
  messages: ChatMessage[];
  isGenerating: boolean;
  copiedIndex: number | null;
  quickPrompts: {title: string, prompt: string}[];
}

export const SUGGEST_STOCKS = [
  { symbol: 'US.AAPL', name: '苹果公司' },
  { symbol: 'US.MSFT', name: '微软' },
  { symbol: 'US.NVDA', name: '英伟达' },
  { symbol: 'US.TSLA', name: '特斯拉' },
  { symbol: 'US.META', name: 'Meta' },
  { symbol: 'US.AMZN', name: '亚马逊' },
  { symbol: 'US.GOOGL', name: '谷歌' },
  { symbol: 'HK.00700', name: '腾讯控股' },
  { symbol: 'HK.03690', name: '美团' },
  { symbol: 'HK.09988', name: '阿里巴巴' },
  { symbol: 'BTC-USD', name: '比特币' },
  { symbol: 'ETH-USD', name: '以太坊' },
]