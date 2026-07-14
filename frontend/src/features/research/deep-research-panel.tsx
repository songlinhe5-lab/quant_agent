'use client'

import React, { useState } from 'react'
import { FileText, Loader2, BookOpen, Sparkles, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

interface ResearchFinding {
  theme: string
  summary: string
  relevance: number
}

interface ResearchReport {
  topic: string
  symbols: string[]
  executive_summary: string
  findings: ResearchFinding[]
  deep_analysis: string
  markdown_content: string
  chart_configs: Record<string, unknown>[]
  references: string[]
}

type PipelineStage = 'idle' | 'cluster' | 'deepdive' | 'delivery' | 'done' | 'error'

const STAGE_LABELS: Record<PipelineStage, string> = {
  idle: '等待开始',
  cluster: '阶段 1/3: 聚类发现',
  deepdive: '阶段 2/3: 数据深挖',
  delivery: '阶段 3/3: 图表交付',
  done: '生成完成',
  error: '生成失败',
}

export function DeepResearchPanel() {
  const { toast } = useToast()
  const [topic, setTopic] = useState('')
  const [symbols, setSymbols] = useState('')
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState<PipelineStage>('idle')
  const [report, setReport] = useState<ResearchReport | null>(null)

  const generateReport = async () => {
    if (!topic.trim()) {
      toast({ variant: 'destructive', title: '请输入研究主题' })
      return
    }

    setLoading(true)
    setReport(null)
    setStage('cluster')

    try {
      // 模拟阶段进度 (实际应使用 SSE)
      setTimeout(() => setStage('deepdive'), 2000)
      setTimeout(() => setStage('delivery'), 4000)

      const symbolList = symbols.split(',').map(s => s.trim()).filter(Boolean)
      const res = await apiClient.post('/research/deep-report', {
        topic: topic.trim(),
        symbols: symbolList,
      })

      if (res.data) {
        setReport(res.data)
        setStage('done')
        toast({ title: '研报生成完成', description: `${res.data.findings?.length || 0} 条核心发现` })
      }
    } catch (e: unknown) {
      setStage('error')
      const errMsg = e instanceof Error ? e.message : '生成失败'
      toast({ variant: 'destructive', title: '研报生成失败', description: errMsg })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="glass-card rounded-xl border border-border/40 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-border/30 bg-secondary/30 flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">AI 深度研报</span>
        <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded font-mono">
          Multi-Agent Pipeline
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* 输入表单 */}
        <div className="space-y-2">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">研究主题</label>
            <Textarea
              placeholder="例如: AI 半导体行业 2024 年趋势分析"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              className="text-sm min-h-[60px]"
              disabled={loading}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">监控标的 (逗号分隔)</label>
            <Input
              placeholder="US.NVDA, US.AMD, US.AVGO, US.TSM"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              className="text-sm font-mono"
              disabled={loading}
            />
          </div>
          <Button
            onClick={generateReport}
            disabled={loading || !topic.trim()}
            className="w-full gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {STAGE_LABELS[stage]}...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                生成深度研报
              </>
            )}
          </Button>
        </div>

        {/* 进度指示 */}
        {loading && (
          <div className="bg-secondary/20 rounded-lg p-3 border border-border/40">
            <div className="flex items-center gap-2 mb-2">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span className="text-xs font-medium">{STAGE_LABELS[stage]}</span>
            </div>
            <div className="w-full bg-secondary rounded-full h-1.5">
              <div
                className="bg-primary h-1.5 rounded-full transition-all duration-1000"
                style={{
                  width: stage === 'cluster' ? '33%' : stage === 'deepdive' ? '66%' : '100%',
                }}
              />
            </div>
          </div>
        )}

        {/* 研报结果 */}
        {report && (
          <div className="space-y-3">
            {/* 核心发现 */}
            {report.findings?.length > 0 && (
              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-amber-500" /> 核心发现
                </h4>
                <div className="space-y-1">
                  {report.findings.map((f, i) => (
                    <div key={i} className="flex items-start gap-2 bg-background/50 rounded-lg px-3 py-2 border border-border/30">
                      <span className="text-[10px] font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded shrink-0">
                        {Math.round(f.relevance * 100)}%
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium">{f.theme}</div>
                        <div className="text-[11px] text-muted-foreground">{f.summary}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 深度分析 */}
            {report.deep_analysis && (
              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-blue-500" /> 深度分析
                </h4>
                <div className="bg-background/50 rounded-lg p-3 border border-border/30 text-xs leading-relaxed whitespace-pre-wrap">
                  {report.deep_analysis}
                </div>
              </div>
            )}

            {/* Markdown 研报 */}
            {report.markdown_content && (
              <details className="space-y-1.5">
                <summary className="text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground">
                  查看完整 Markdown 研报
                </summary>
                <pre className="bg-background/50 rounded-lg p-3 border border-border/30 text-[10px] leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-96 custom-scrollbar">
                  {report.markdown_content}
                </pre>
              </details>
            )}
          </div>
        )}

        {/* 空状态 */}
        {!loading && !report && stage === 'idle' && (
          <div className="text-center py-8 text-muted-foreground">
            <BookOpen className="h-10 w-10 mx-auto mb-3 opacity-20" />
            <p className="text-xs">输入研究主题和监控标的，AI 将生成深度研报</p>
            <p className="text-[10px] mt-1">三段流水线: 聚类发现 → 数据深挖 → 图表交付</p>
          </div>
        )}

        {/* 错误状态 */}
        {stage === 'error' && (
          <div className="flex items-center gap-2 text-red-500 text-xs bg-red-500/5 rounded-lg p-3 border border-red-500/20">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>研报生成失败，请检查 LLM 服务状态后重试</span>
          </div>
        )}
      </div>
    </div>
  )
}
