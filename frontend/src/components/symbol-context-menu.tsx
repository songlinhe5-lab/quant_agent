'use client'

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { Bell, Brain, Copy, Eye, LineChart, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { useToast } from '@/hooks/use-toast'

type SymbolContextMenuProps = {
  symbol: string
  children: React.ReactNode
  onRemove?: (symbol: string) => void
  onSelect?: (symbol: string) => void
}

/**
 * FE-12: 行情/自选右键菜单 — 分析 / 自选 / 复制 / 告警
 */
export function SymbolContextMenu({ symbol, children, onRemove, onSelect }: SymbolContextMenuProps) {
  const navigate = useNavigate()
  const openCopilot = useLayoutStore((s) => s.openCopilot)
  const { toast } = useToast()

  const copySymbol = async () => {
    try {
      await navigator.clipboard.writeText(symbol)
      toast({ title: '已复制', description: symbol })
    } catch {
      toast({ variant: 'destructive', title: '复制失败' })
    }
  }

  const openQuotes = () => {
    onSelect?.(symbol)
    sessionStorage.setItem('quant_target_symbol', symbol)
    navigate('/quotes')
  }

  const askAi = () => {
    openCopilot()
    window.dispatchEvent(
      new CustomEvent('copilot-prefill', {
        detail: { prompt: `请分析 ${symbol} 的最新走势与风险点` },
      }),
    )
  }

  const setAlert = () => {
    window.dispatchEvent(new CustomEvent('open-alert-create', { detail: { ticker: symbol } }))
    navigate('/alerts')
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent className="w-48" data-testid="symbol-context-menu">
        <ContextMenuItem onClick={openQuotes} className="gap-2 text-xs">
          <LineChart className="h-3.5 w-3.5" /> 查看行情
        </ContextMenuItem>
        <ContextMenuItem onClick={askAi} className="gap-2 text-xs">
          <Brain className="h-3.5 w-3.5" /> 问 AI 分析
        </ContextMenuItem>
        <ContextMenuItem onClick={copySymbol} className="gap-2 text-xs">
          <Copy className="h-3.5 w-3.5" /> 复制代码
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onClick={setAlert} className="gap-2 text-xs">
          <Bell className="h-3.5 w-3.5" /> 设置价格告警
        </ContextMenuItem>
        {onRemove && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem
              onClick={() => onRemove(symbol)}
              className="gap-2 text-xs text-red-400 focus:text-red-400"
            >
              <Trash2 className="h-3.5 w-3.5" /> 移出自选
            </ContextMenuItem>
          </>
        )}
        {!onRemove && (
          <ContextMenuItem
            onClick={() => {
              window.dispatchEvent(new CustomEvent('watchlist-add', { detail: { ticker: symbol } }))
              toast({ title: '已加入自选', description: symbol })
            }}
            className="gap-2 text-xs"
          >
            <Eye className="h-3.5 w-3.5" /> 加入自选
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
