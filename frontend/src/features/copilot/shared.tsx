import React from 'react'
import { Code2, Globe, ShieldAlert, LineChart, FileText, Lightbulb } from 'lucide-react'

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

export const getIconForTitle = (title: string) => {
  if (title.includes('策略') || title.includes('代码') || title.includes('Debug') || title.includes('因子')) return <Code2 className="h-4 w-4 text-violet-400" />
  if (title.includes('宏观') || title.includes('资产') || title.includes('流动性') || title.includes('套利')) return <Globe className="h-4 w-4 text-blue-400" />
  if (title.includes('风向') || title.includes('情绪') || title.includes('黑天鹅') || title.includes('预警') || title.includes('风控')) return <ShieldAlert className="h-4 w-4 text-amber-400" />
  if (title.includes('技术面') || title.includes('诊股') || title.includes('轮动') || title.includes('订单簿')) return <LineChart className="h-4 w-4 text-emerald-400" />
  if (title.includes('研报') || title.includes('组合') || title.includes('投资') || title.includes('排雷')) return <FileText className="h-4 w-4 text-sky-400" />
  return <Lightbulb className="h-4 w-4 text-primary" />
}