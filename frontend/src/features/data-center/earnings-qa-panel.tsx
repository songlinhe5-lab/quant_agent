import { useState, useRef, useEffect } from 'react'
import { FileText, Send, AlertTriangle, Quote } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'

interface Citation {
  content: string
  url: string
  score?: number
}
interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  status?: 'success' | 'warning' | 'error'
  message?: string
}

export function EarningsQAPanel() {
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [loading, setLoading] = useState(false)
  const [conversationId] = useState(() => `earn_${Date.now().toString(36)}`)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, loading])

  const ask = async () => {
    const q = input.trim()
    if (!q || loading) return
    const history = turns
      .filter((t) => t.role === 'user' || t.role === 'assistant')
      .map((t) => ({ role: t.role, content: t.content }))
    setTurns((p) => [...p, { role: 'user', content: q }])
    setInput('')
    setLoading(true)
    try {
      const res = await apiClient.post('/api/v1/rag/chat', {
        question: q,
        history,
        conversation_id: conversationId,
      })
      const body = res.data || res
      if (body.status === 'success') {
        setTurns((p) => [
          ...p,
          { role: 'assistant', content: body.answer || '', citations: body.citations || [], status: 'success' },
        ])
      } else {
        setTurns((p) => [
          ...p,
          {
            role: 'assistant',
            content: body.message || '暂无回答',
            status: body.status || 'warning',
            message: body.message,
          },
        ])
      }
    } catch (e: any) {
      setTurns((p) => [
        ...p,
        {
          role: 'assistant',
          content: e?.response?.data?.message || '问答服务调用失败',
          status: 'error',
          message: String(e),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto">
      <div className="flex items-center gap-2 px-1 pb-2">
        <FileText className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold text-foreground">财报 / 研报智能问答</span>
        <span className="ml-auto text-[10px] text-muted-foreground">RAG · 仅基于已入库财报片段作答</span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto custom-scrollbar space-y-3 pr-1">
        {turns.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <AlertTriangle className="h-5 w-5 text-muted-foreground/40" />
            <p className="text-[12px] text-muted-foreground">
              向知识库中的财报 / 研报提问，例如「某公司 2026H1 毛利率变化及原因？」
            </p>
            <p className="text-[10px] text-muted-foreground/60">
              需先经 scripts/ingest_local_reports.py 灌库且 Embedding / LLM 服务可用
            </p>
          </div>
        )}

        {turns.map((t, i) => (
          <div key={i} className={cn('flex', t.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div
              className={cn(
                'max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed',
                t.role === 'user'
                  ? 'bg-primary/20 text-foreground'
                  : t.status === 'error'
                    ? 'bg-rose-500/10 text-rose-300 border border-rose-500/30'
                    : t.status === 'warning'
                      ? 'bg-amber-500/10 text-amber-200 border border-amber-500/30'
                      : 'bg-card/60 text-foreground border border-border/30',
              )}
            >
              <p className="whitespace-pre-wrap">{t.content}</p>
              {t.citations && t.citations.length > 0 && (
                <div className="mt-2 pt-2 border-t border-border/20 space-y-1.5">
                  <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                    <Quote className="h-3 w-3" /> 引用来源（{t.citations.length}）
                  </span>
                  {t.citations.map((c, ci) => (
                    <div key={ci} className="text-[10px] text-muted-foreground/80 rounded bg-background/40 px-2 py-1">
                      <span className="text-primary/80">{c.url}</span>
                      {c.score != null && <span className="ml-1 text-muted-foreground/50">· 相关度 {c.score}</span>}
                      <p className="mt-0.5 line-clamp-3">{c.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="rounded-lg px-3 py-2 text-[13px] bg-card/60 text-muted-foreground border border-border/30">
              检索知识库中…
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-border/20">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask()}
          placeholder="输入财报 / 研报相关问题…"
          className="flex-1 rounded-lg bg-background/60 border border-border/40 px-3 py-2 text-[13px] text-foreground outline-none focus:border-primary/50"
        />
        <button
          onClick={ask}
          disabled={loading || !input.trim()}
          className={cn(
            'rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
            loading || !input.trim()
              ? 'bg-secondary text-muted-foreground cursor-not-allowed'
              : 'bg-primary text-primary-foreground hover:bg-primary/90',
          )}
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
