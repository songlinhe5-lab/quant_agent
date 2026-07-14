/**
 * STRAT-02: Diff 覆盖层组件
 * 使用 Monaco DiffEditor 展示 AI 生成的代码差异，提供 Apply/Reject 操作
 */
import React, { useRef, useEffect } from 'react'
import Editor, { useMonaco } from '@monaco-editor/react'
import * as monaco_editor from 'monaco-editor'
import { useTheme } from 'next-themes'
import { Check, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStrategyStore } from '../stores'
import { cn } from '@/lib/utils'

// Monaco Environment setup (same as monaco-editor.tsx)
if (typeof window !== 'undefined') {
  (window as any).MonacoEnvironment = {
    getWorker: () => new Worker(new URL('monaco-editor/esm/vs/editor/editor.worker.js', import.meta.url), { type: 'module' })
  }
}
import { loader } from '@monaco-editor/react'
loader.config({ monaco: monaco_editor })

const SOURCE_LABELS: Record<string, string> = {
  'ai-chat': 'AI Copilot',
  'auto-fix': 'Auto-Debug',
  'ast-fix': 'AST 修复',
  'hermes': 'Hermes 部署',
  'version-restore': '版本恢复',
}

export function DiffOverlay() {
  const { theme } = useTheme()
  const monaco = useMonaco()
  const diffEditorRef = useRef<any>(null)
  
  const { diff, applyDiff, rejectDiff } = useStrategyStore()

  useEffect(() => {
    if (monaco && diffEditorRef.current) {
      // Configure diff editor theme
      monaco.editor.defineTheme('quant-dark-diff', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
          { token: 'keyword', foreground: 'c586c0' },
          { token: 'string', foreground: '10b981' },
        ],
        colors: {
          'editor.background': '#00000000',
          'diffEditor.insertedTextBackground': '#10b98120',
          'diffEditor.removedTextBackground': '#ef444420',
        }
      })
    }
  }, [monaco])

  if (diff.status !== 'pendingDiff') return null

  const sourceLabel = SOURCE_LABELS[diff.source] || diff.source

  return (
    <div className="flex flex-col h-full w-full bg-slate-50 dark:bg-[oklch(0.09_0.005_270)]">
      {/* Top Action Bar */}
      <div className="h-10 px-4 border-b border-border/40 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-red-500/10 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-amber-500" />
          <span className="text-xs font-bold text-foreground">
            AI 代码变更审查
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-mono">
            来源: {sourceLabel}
          </span>
          {diff.meta?.versionId && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-500 font-mono">
              v{diff.meta.versionId.slice(0, 8)}
            </span>
          )}
          {diff.meta?.errorRef && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-500 font-mono">
              修复: {diff.meta.errorRef.slice(0, 8)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={rejectDiff}
            className="h-7 text-xs gap-1.5 border-red-500/30 text-red-500 hover:bg-red-500/10"
          >
            <X className="h-3.5 w-3.5" /> 拒绝
          </Button>
          <Button
            size="sm"
            onClick={applyDiff}
            className="h-7 text-xs gap-1.5 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30"
          >
            <Check className="h-3.5 w-3.5" /> 应用
          </Button>
        </div>
      </div>

      {/* Diff Editor: Side-by-side view using two regular editors */}
      <div className="flex-1 relative w-full flex">
        <div className="flex-1 flex flex-col border-r border-border/40">
          <div className="h-6 px-3 bg-red-500/5 border-b border-border/30 flex items-center">
            <span className="text-[10px] font-bold text-red-500 uppercase">原始代码</span>
          </div>
          <Editor
            height="calc(100% - 24px)"
            language="python"
            theme={theme === 'dark' ? 'quant-dark' : 'vs-light'}
            value={diff.original}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 12,
              lineHeight: 20,
              scrollBeyondLastLine: false,
            }}
          />
        </div>
        <div className="flex-1 flex flex-col">
          <div className="h-6 px-3 bg-emerald-500/5 border-b border-border/30 flex items-center">
            <span className="text-[10px] font-bold text-emerald-500 uppercase">AI 生成代码</span>
          </div>
          <Editor
            height="calc(100% - 24px)"
            language="python"
            theme={theme === 'dark' ? 'quant-dark' : 'vs-light'}
            value={diff.incoming}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 12,
              lineHeight: 20,
              scrollBeyondLastLine: false,
            }}
          />
        </div>
      </div>
    </div>
  )
}
