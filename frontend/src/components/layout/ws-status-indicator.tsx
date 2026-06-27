'use client'

import { useSystemStore } from '@/stores/useSystemStore'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export function WsStatusIndicator() {
  const wsStatus = useSystemStore((state) => state.wsStatus)

  const statusConfig = {
    CONNECTED: {
      color: 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse',
      text: '实时推送已连接',
    },
    CONNECTING: {
      color: 'bg-amber-500 animate-pulse',
      text: '正在连接...',
    },
    DISCONNECTED: {
      color: 'bg-red-500',
      text: '推送已断开',
    }
  }

  const currentStatus = statusConfig[wsStatus]

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="fixed bottom-4 right-4 z-50 h-3 w-3 rounded-full border-2 border-background shadow-md cursor-help">
             <div className={cn('h-full w-full rounded-full', currentStatus.color)} />
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p className="text-xs font-mono">{currentStatus.text}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}