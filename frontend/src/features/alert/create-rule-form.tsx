/**
 * 新建告警规则表单（Modal）
 */

import React, { useState } from 'react'
import { X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AlertRuleType, AlertSeverity, AlertChannel, CreateRulePayload } from '@/types/alert'
import { RULE_TYPE_LABELS, SEVERITY_LABELS } from '@/types/alert'

interface CreateRuleFormProps {
  prefillTicker?: string
  onSubmit: (payload: CreateRulePayload) => Promise<void>
  onClose: () => void
}

export function CreateRuleForm({ prefillTicker, onSubmit, onClose }: CreateRuleFormProps) {
  const [name, setName] = useState('')
  const [ticker, setTicker] = useState(prefillTicker || '')
  const [ruleType, setRuleType] = useState<AlertRuleType>('price_above')
  const [threshold, setThreshold] = useState('')
  const [severity, setSeverity] = useState<AlertSeverity>('warning')
  const [channels, setChannels] = useState<AlertChannel[]>(['in_app'])
  const [cooldown, setCooldown] = useState(300)
  const [submitting, setSubmitting] = useState(false)
  // ALERT-05: 指标类规则额外字段
  const [direction, setDirection] = useState<'golden' | 'death'>('golden')
  const [shortPeriod, setShortPeriod] = useState(10)
  const [longPeriod, setLongPeriod] = useState(20)

  const isIndicatorRule = ['rsi_threshold', 'macd_cross', 'ma_cross'].includes(ruleType)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !ticker) return
    if (!isIndicatorRule && !threshold) return

    setSubmitting(true)

    const metadata: Record<string, unknown> = {}
    if (ruleType === 'macd_cross') {
      metadata.direction = direction
    } else if (ruleType === 'ma_cross') {
      metadata.direction = direction
      metadata.short_period = shortPeriod
      metadata.long_period = longPeriod
    }

    await onSubmit({
      name,
      ticker: ticker.toUpperCase(),
      rule_type: ruleType,
      threshold: threshold ? parseFloat(threshold) : 0,
      severity,
      channels,
      cooldown_seconds: cooldown,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    })
    setSubmitting(false)
  }

  const toggleChannel = (ch: AlertChannel) => {
    setChannels(prev => prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div className="w-[440px] bg-background border border-border/60 rounded-xl shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/40">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-bold">新建告警规则</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary/80 text-muted-foreground"><X className="h-4 w-4" /></button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">规则名称</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="如: AAPL 突破 $200" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50" required />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">标的代码</label>
              <input type="text" value={ticker} onChange={e => setTicker(e.target.value)} placeholder="AAPL / 00700.HK" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" required />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">告警类型</label>
              <select value={ruleType} onChange={e => setRuleType(e.target.value as AlertRuleType)} className="w-full h-8 px-2 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50">
                {Object.entries(RULE_TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          {/* RSI 阈值 */}
          {ruleType === 'rsi_threshold' && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">RSI 阈值</label>
              <input type="number" step="1" min="1" max="99" value={threshold} onChange={e => setThreshold(e.target.value)} placeholder="30 = 超卖告警, 70 = 超买告警" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" required />
              <p className="text-[10px] text-muted-foreground mt-1">≤50 触发 RSI 低于阈值（超卖），&gt;50 触发 RSI 高于阈值（超买）</p>
            </div>
          )}

          {/* MACD 穿越方向 */}
          {ruleType === 'macd_cross' && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">穿越方向</label>
              <div className="flex gap-2">
                <button type="button" onClick={() => setDirection('golden')} className={cn('px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors', direction === 'golden' ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-600' : 'bg-secondary/20 border-border/50 text-muted-foreground')}>
                  🟢 金叉（MACD 上穿 Signal）
                </button>
                <button type="button" onClick={() => setDirection('death')} className={cn('px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors', direction === 'death' ? 'bg-red-500/10 border-red-500/50 text-red-600' : 'bg-secondary/20 border-border/50 text-muted-foreground')}>
                  🔴 死叉（MACD 下穿 Signal）
                </button>
              </div>
            </div>
          )}

          {/* MA 穿越 */}
          {ruleType === 'ma_cross' && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">短期均线周期</label>
                  <input type="number" value={shortPeriod} onChange={e => setShortPeriod(parseInt(e.target.value) || 10)} min="2" max="200" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">长期均线周期</label>
                  <input type="number" value={longPeriod} onChange={e => setLongPeriod(parseInt(e.target.value) || 20)} min="2" max="200" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" />
                </div>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">穿越方向</label>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setDirection('golden')} className={cn('px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors', direction === 'golden' ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-600' : 'bg-secondary/20 border-border/50 text-muted-foreground')}>
                    🟢 金叉（短均上穿长均）
                  </button>
                  <button type="button" onClick={() => setDirection('death')} className={cn('px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors', direction === 'death' ? 'bg-red-500/10 border-red-500/50 text-red-600' : 'bg-secondary/20 border-border/50 text-muted-foreground')}>
                    🔴 死叉（短均下穿长均）
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* 通用阈值 */}
          {!isIndicatorRule && (
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">阈值</label>
              <input type="number" step="any" value={threshold} onChange={e => setThreshold(e.target.value)} placeholder="触发价格或指标值" className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" required />
            </div>
          )}

          {/* Severity + Cooldown */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">严重级别</label>
              <select value={severity} onChange={e => setSeverity(e.target.value as AlertSeverity)} className="w-full h-8 px-2 bg-secondary/30 border border-border/50 rounded-md text-xs focus:outline-none focus:border-primary/50">
                {Object.entries(SEVERITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">冷却时间 (秒)</label>
              <input type="number" value={cooldown} onChange={e => setCooldown(parseInt(e.target.value) || 300)} min={60} className="w-full h-8 px-3 bg-secondary/30 border border-border/50 rounded-md text-xs font-mono focus:outline-none focus:border-primary/50" />
            </div>
          </div>

          {/* Channels */}
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground mb-1.5 block">推送通道</label>
            <div className="flex gap-2">
              {(['in_app', 'feishu', 'telegram'] as AlertChannel[]).map(ch => (
                <button key={ch} type="button" onClick={() => toggleChannel(ch)} className={cn('px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors', channels.includes(ch) ? 'bg-primary/10 border-primary/50 text-primary' : 'bg-secondary/20 border-border/50 text-muted-foreground hover:border-primary/30')}>
                  {ch === 'in_app' ? '应用内' : ch === 'feishu' ? '飞书' : 'Telegram'}
                </button>
              ))}
            </div>
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose} className="h-8 text-xs">取消</Button>
            <Button type="submit" size="sm" disabled={submitting || !name || !ticker || (!isIndicatorRule && !threshold)} className="h-8 text-xs">
              {submitting ? '创建中...' : '创建规则'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
