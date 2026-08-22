import { useState, useEffect } from 'react'
import { Sparkles, AlertTriangle, ListOrdered, Lightbulb } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { useAiPushPrefStore } from '@/stores/useAiPushPrefStore'

interface TriageResult {
  summary?: string
  correlation?: string
  priority_order?: string[]
  rule_suggestion?: string
}

// AI-06 告警分诊员：关联分析 + 智能排序 + 规则建议。受 ai06 开关控制，无 LLM/无告警时降级占位。
export function AiTriageCard({ alerts }: { alerts?: any[] }) {
  const ai06Enabled = useAiPushPrefStore((s) => s.isEnabled('ai06'))
  const [loading, setLoading] = useState(false)
  const [triage, setTriage] = useState<TriageResult | null>(null)
  const [warn, setWarn] = useState<string | null>(null)

  useEffect(() => {
    if (!ai06Enabled) return
    const input = (alerts || [])
      .slice(0, 30)
      .map((a) => ({
        symbol: a.symbol || a.ticker || '?',
        type: a.type || a.category || '?',
        detail: a.detail || a.message || '',
      }))
    if (!input.length) {
      setTriage(null)
      setWarn('暂无触发告警，分诊待命中')
      setLoading(false)
      return
    }
    let alive = true
    setLoading(true)
    setWarn(null)
    ;(async () => {
      try {
        const res = await apiClient.post('/alert/ai-triage', { alerts: input })
        const body = res.data || res
        if (body.status === 'success' && body.triage) {
          if (alive) setTriage(body.triage)
        } else {
          if (alive) setWarn(body.message || '分诊暂不可用')
        }
      } catch (e: any) {
        if (alive) setWarn(e?.response?.data?.message || '分诊服务调用失败')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [ai06Enabled, alerts])

  if (!ai06Enabled) return null

  return (
    <div className="glass-card rounded-lg p-3 flex flex-col gap-2 border border-primary/15">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-primary">
        <Sparkles className="h-3.5 w-3.5" />
        AI 告警分诊员
        {loading && <span className="ml-auto text-[9px] text-muted-foreground animate-pulse">分析中…</span>}
      </div>

      {warn && !triage && (
        <div className="flex items-center gap-1.5 text-[10px] text-amber-300/80">
          <AlertTriangle className="h-3 w-3" />
          {warn}
        </div>
      )}

      {triage && (
        <div className="space-y-2 text-[10px] leading-relaxed">
          {triage.summary && <p className="text-foreground/90">{triage.summary}</p>}
          {triage.correlation && (
            <p className="text-muted-foreground">
              <span className="text-primary/80">关联：</span>
              {triage.correlation}
            </p>
          )}
          {triage.priority_order && triage.priority_order.length > 0 && (
            <div className="flex items-start gap-1.5">
              <ListOrdered className="h-3 w-3 mt-0.5 text-primary/80 shrink-0" />
              <div>
                <span className="text-primary/80">优先级：</span>
                {triage.priority_order.map((p, i) => (
                  <span key={i} className="inline-block mr-1 px-1 rounded bg-secondary/40 text-foreground/80">
                    {i + 1}. {p}
                  </span>
                ))}
              </div>
            </div>
          )}
          {triage.rule_suggestion && (
            <p className="text-muted-foreground">
              <Lightbulb className="h-3 w-3 inline mr-1 text-primary/80" />
              {triage.rule_suggestion}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
