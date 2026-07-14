/**
 * STRAT-03b: 版本时间线组件
 * 展示策略的版本历史，支持点击恢复
 */
import React, { useEffect, useState } from 'react'
import { Clock, GitCommit, RotateCcw, Loader2 } from 'lucide-react'
import { useStrategyStore } from '../stores'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

interface Version {
  id: string
  seq: number
  source: string
  message: string | null
  code_hash: string
  parent_id: string | null
  created_at: string | null
}

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  manual: { label: '手动', className: 'bg-blue-500/10 text-blue-500 border-blue-500/30' },
  'ai-apply': { label: 'AI', className: 'bg-purple-500/10 text-purple-500 border-purple-500/30' },
  'auto-fix': { label: '修复', className: 'bg-amber-500/10 text-amber-500 border-amber-500/30' },
  'ast-fix': { label: 'AST', className: 'bg-orange-500/10 text-orange-500 border-orange-500/30' },
  restore: { label: '恢复', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30' },
}

export function VersionTimeline() {
  const { activeStrategy, enterDiff } = useStrategyStore()
  const { toast } = useToast()
  const [versions, setVersions] = useState<Version[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (!activeStrategy) {
      setVersions([])
      return
    }

    const fetchVersions = async () => {
      setIsLoading(true)
      try {
        const res = await apiClient.get(`/strategy/${activeStrategy}/versions?limit=50`)
        if (res.data?.status === 'success') {
          setVersions(res.data.data)
        }
      } catch (e) {
        console.error('Failed to fetch versions:', e)
      } finally {
        setIsLoading(false)
      }
    }

    fetchVersions()
  }, [activeStrategy])

  const handleRestore = async (versionId: string) => {
    if (!activeStrategy) return

    try {
      // 获取版本全文
      const res = await apiClient.get(`/strategy/versions/${versionId}`)
      if (res.data?.status === 'success') {
        const code = res.data.data.code
        enterDiff(code, 'version-restore', { versionId })
        toast({ title: '✅ 版本已加载', description: '请在 Diff 编辑器中审查并确认恢复。' })
      } else {
        toast({ variant: 'destructive', title: '加载失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    }
  }

  if (!activeStrategy) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-xs font-mono opacity-50 p-4">
        <Clock className="h-6 w-6 mb-2 opacity-30" />
        <span>请先选择一个策略</span>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (versions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-xs font-mono opacity-50 p-4">
        <GitCommit className="h-6 w-6 mb-2 opacity-30" />
        <span>暂无版本记录</span>
        <span className="text-[10px] mt-1">保存策略后将自动创建版本</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="h-8 px-3 border-b border-border/30 flex items-center shrink-0 bg-secondary/10">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" /> 版本时间线 ({versions.length})
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
        {versions.map((v) => {
          const sourceStyle = SOURCE_STYLES[v.source] || SOURCE_STYLES.manual
          return (
            <div
              key={v.id}
              className="group relative rounded-md border border-border/30 hover:border-primary/50 transition-colors p-2 cursor-pointer"
              onClick={() => handleRestore(v.id)}
            >
              <div className="flex items-start justify-between gap-2 mb-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold text-foreground">v{v.seq}</span>
                  <span
                    className={cn(
                      'text-[9px] px-1.5 py-0.5 rounded border font-medium',
                      sourceStyle.className
                    )}
                  >
                    {sourceStyle.label}
                  </span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleRestore(v.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-all"
                  title="恢复此版本"
                >
                  <RotateCcw className="h-3 w-3" />
                </button>
              </div>
              {v.message && (
                <p className="text-[10px] text-muted-foreground line-clamp-2 mb-1">{v.message}</p>
              )}
              <div className="flex items-center gap-2 text-[9px] text-muted-foreground/70 font-mono">
                <span>#{v.code_hash}</span>
                {v.created_at && (
                  <span>{new Date(v.created_at).toLocaleDateString()}</span>
                )}
              </div>
              {v.parent_id && (
                <div className="mt-1 text-[9px] text-emerald-500/70 font-mono">
                  ← 恢复自 #{v.parent_id.slice(0, 8)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
