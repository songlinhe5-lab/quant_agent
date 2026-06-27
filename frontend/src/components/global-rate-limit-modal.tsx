'use client'

import React, { useState, useEffect } from 'react'
import { ShieldAlert, AlertOctagon, Hourglass } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export function GlobalRateLimitModal() {
  const [isOpen, setIsOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState(429)
  const [countdown, setCountdown] = useState(0)

  useEffect(() => {
    const handleRateLimit = (e: Event) => {
      const customEvent = e as CustomEvent<{ status: number; message: string }>
      const { status: errStatus, message: errMsg } = customEvent.detail
      
      setStatus(errStatus)
      setMessage(errMsg)
      setIsOpen(true)

      // 智能解析后端返回文本中的倒计时
      let seconds = 60 // 默认 60 秒
      if (errMsg.includes('24 小时')) {
        seconds = 86400
      } else if (errMsg.includes('10秒')) {
        seconds = 10
      } else if (errMsg.includes('60秒')) {
        seconds = 60
      }
      setCountdown(seconds)
    }

    window.addEventListener('quant-rate-limit', handleRateLimit)
    return () => window.removeEventListener('quant-rate-limit', handleRateLimit)
  }, [])

  useEffect(() => {
    let timer: NodeJS.Timeout
    if (isOpen && countdown > 0) {
      timer = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            setIsOpen(false) // 倒计时结束，自动解除弹窗
            return 0
          }
          return prev - 1
        })
      }, 1000)
    }
    return () => clearInterval(timer)
  }, [isOpen, countdown])

  if (!isOpen) return null

  const isBanned = status === 403
  const formatTime = (totalSeconds: number) => {
    if (totalSeconds < 60) return `${totalSeconds} 秒`
    const h = Math.floor(totalSeconds / 3600)
    const m = Math.floor((totalSeconds % 3600) / 60)
    const s = totalSeconds % 60
    if (h > 0) return `${h}小时 ${m}分 ${s}秒`
    return `${m}分 ${s}秒`
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-md mx-4 overflow-hidden rounded-2xl border bg-background/95 backdrop-blur-xl shadow-2xl p-6 animate-in zoom-in-95 duration-300">
        
        {/* 顶部动态色彩条 */}
        <div className={cn(
          "absolute top-0 left-0 w-full h-1.5", 
          isBanned ? "bg-red-500" : "bg-amber-500"
        )} />

        <div className="flex flex-col items-center text-center space-y-4 mt-2">
          <div className={cn(
            "p-4 rounded-full border", 
            isBanned ? "bg-red-500/10 border-red-500/20 text-red-500" : "bg-amber-500/10 border-amber-500/20 text-amber-500"
          )}>
            {isBanned ? <AlertOctagon className="h-10 w-10" /> : <ShieldAlert className="h-10 w-10" />}
          </div>
          
          <div className="space-y-2">
            <h2 className="text-lg font-bold tracking-tight text-foreground">
              {isBanned ? '触发系统级风控熔断' : '操作过于频繁'}
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {message}
            </p>
          </div>

          <div className="w-full p-4 mt-4 rounded-xl bg-secondary/30 border border-border/50 flex flex-col items-center gap-2">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">冷却倒计时</span>
            <div className="flex items-center gap-2 text-2xl font-mono font-bold text-foreground">
              <Hourglass className="h-5 w-5 animate-pulse text-muted-foreground" />
              {formatTime(countdown)}
            </div>
          </div>

          {!isBanned && (
            <Button variant="outline" className="w-full mt-4" onClick={() => setIsOpen(false)}>
              我已知晓，不再连续点击
            </Button>
          )}
          
        </div>
      </div>
    </div>
  )
}