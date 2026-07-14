'use client'

import React, { type MutableRefObject } from 'react'
import { Bot, Play, Pause, PowerOff, Cpu, MemoryStick } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LiveBot } from './oms-types'

interface OmsBotGridProps {
  bots: LiveBot[]
  isKilled: boolean
  logsEndRefs: MutableRefObject<{ [key: string]: HTMLDivElement | null }>
  onToggleBotStatus: (botId: string, currentStatus: string) => void
  onStopBot: (botId: string) => void
}

export function OmsBotGrid({
  bots,
  isKilled,
  logsEndRefs,
  onToggleBotStatus,
  onStopBot,
}: OmsBotGridProps) {
  return (
    <div className={cn("flex-1 overflow-y-auto custom-scrollbar pb-[400px] transition-all", isKilled && "saturate-0 opacity-80")}>
      <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4 p-1">
        {bots.map(bot => (
          <div key={bot.id} className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm flex flex-col h-[320px] transition-all hover:border-primary/30">
            
            {/* Bot Header */}
            <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className={cn(
                  "p-1.5 rounded-md text-white shadow-sm",
                  bot.status === 'running' ? "bg-emerald-500" : bot.status === 'paused' ? "bg-amber-500" : "bg-red-500"
                )}>
                  <Bot className="w-4 h-4" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-bold tracking-tight leading-none">{bot.name}</span>
                  <span className="text-[10px] text-muted-foreground font-mono mt-1">{bot.ticker}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn(
                  "text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider border",
                  bot.status === 'running' ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" : 
                  bot.status === 'paused' ? "bg-amber-500/10 text-amber-600 border-amber-500/20" : 
                  "bg-red-500/10 text-red-600 border-red-500/20"
                )}>
                  {bot.status}
                </span>
                <button 
                  onClick={() => onToggleBotStatus(bot.id, bot.status)}
                  disabled={bot.status === 'error' || bot.status === 'stopped'}
                  className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50 disabled:cursor-not-allowed" 
                  title={bot.status === 'running' ? '暂停执行' : bot.status === 'paused' ? '恢复执行' : '节点已终止'}
                >
                  {bot.status === 'running' ? <Pause className="w-3.5 h-3.5" /> : bot.status === 'paused' ? <Play className="w-3.5 h-3.5" /> : <PowerOff className="w-3.5 h-3.5" />}
                </button>
                {(bot.status === 'running' || bot.status === 'paused') && (
                  <button 
                    onClick={() => onStopBot(bot.id)}
                    className="p-1 rounded text-red-500/70 hover:text-red-400 hover:bg-red-500/10 transition-colors" 
                    title="终止 Bot"
                  >
                    <PowerOff className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
            
            {/* Micro Resource Indicators */}
            <div className="px-4 py-3 border-b border-border/20 grid grid-cols-2 gap-4 bg-background/50">
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-[10px] font-mono text-muted-foreground">
                  <span className="flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
                  <span>{bot.cpu.toFixed(1)}%</span>
                </div>
                <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
                  <div className="h-full bg-indigo-500 transition-all duration-500" style={{ width: `${bot.cpu}%` }} />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-[10px] font-mono text-muted-foreground">
                  <span className="flex items-center gap-1"><MemoryStick className="w-3 h-3" /> MEM</span>
                  <span>{bot.mem.toFixed(0)} MB</span>
                </div>
                <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
                  <div className="h-full bg-sky-500 transition-all duration-500" style={{ width: `${(bot.mem / 512) * 100}%` }} />
                </div>
              </div>
            </div>

            {/* Cyberpunk Terminal Logs */}
            <div className="flex-1 bg-[#0a0a0a] dark:bg-black p-3 overflow-y-auto custom-scrollbar font-mono text-[10px] leading-relaxed relative">
              {bot.logs.map((log, idx) => (
                <div key={idx} className="flex items-start gap-2 mb-1.5 opacity-90 hover:opacity-100">
                  <span className="text-slate-500 shrink-0">[{log.time}]</span>
                  <span className={cn(
                    "break-words",
                    log.type === 'success' ? "text-emerald-400" : 
                    log.type === 'warn' ? "text-amber-400" : 
                    "text-slate-300"
                  )}>
                    {log.msg}
                  </span>
                </div>
              ))}
              <div ref={(el) => { logsEndRefs.current[bot.id] = el }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
