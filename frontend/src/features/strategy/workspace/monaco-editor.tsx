import React, { useState, useEffect, useRef } from 'react'
import Editor, { useMonaco, loader } from '@monaco-editor/react'
import * as monaco_editor from 'monaco-editor'
import { useTheme } from 'next-themes'
import { useToast } from '@/hooks/use-toast'
import { Loader2, Play, Save, AlertCircle, Bot } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient, API_BASE_URL, getAccessToken } from '@/lib/api-client'
import { useStrategyStore } from '../stores/useStrategyStore'

// 💡 终极离线方案 (ESM Bundling)：直接让打包工具自动提取并构建依赖
if (typeof window !== 'undefined') {
  (window as any).MonacoEnvironment = {
    getWorker: () => new Worker(new URL('monaco-editor/esm/vs/editor/editor.worker.js', import.meta.url), { type: 'module' })
  }
}
loader.config({ monaco: monaco_editor })

export function MonacoEditorTab() {
  const store = useStrategyStore()
  const { theme } = useTheme()
  const { toast } = useToast()
  const monaco = useMonaco()
  const editorRef = useRef<any>(null)
  
  const [isChecking, setIsChecking] = useState(false)
  const [syntaxError, setSyntaxError] = useState<{line: number, msg: string} | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isFixing, setIsFixing] = useState(false)

  // 💡 配置 Monaco Editor 的高级赛博朋克量化主题与格式化器
  useEffect(() => {
    if (monaco) {
      monaco.editor.defineTheme('quant-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
          { token: 'keyword', foreground: 'c586c0' },
          { token: 'string', foreground: '10b981' },
        ],
        colors: {
          'editor.background': '#00000000', // 极致透明，透出父组件的玻璃态背景
          'editor.lineHighlightBackground': '#ffffff0a',
          'editorLineNumber.foreground': '#475569',
        }
      })
      monaco.editor.defineTheme('quant-light', {
        base: 'vs',
        inherit: true,
        rules: [],
        colors: {
          'editor.background': '#ffffff00',
          'editor.lineHighlightBackground': '#0000000a',
        }
      })

      // 💡 注册 Python 格式化提供者 (接入后端的 Black)
      const formatProvider = monaco.languages.registerDocumentFormattingEditProvider('python', {
        async provideDocumentFormattingEdits(model) {
          try {
            const res = await apiClient.post('/strategy/format', { source_code: model.getValue() })
            if (res.data?.status === 'success' && res.data.data) {
              return [{ range: model.getFullModelRange(), text: res.data.data }]
            }
          } catch (e) { console.error('Format failed', e) }
          return []
        }
      })
      
      // 💡 注册 Python 智能代码补全 (Pandas & Numpy 核心量化方法)
      const completionProvider = monaco.languages.registerCompletionItemProvider('python', {
        triggerCharacters: ['.'],
        provideCompletionItems: (model, position) => {
          const lineContent = model.getLineContent(position.lineNumber)
          const textUntilPosition = lineContent.substring(0, position.column - 1)
          const suggestions: any[] = []

          if (textUntilPosition.endsWith('pd.')) {
            suggestions.push(
              { label: 'DataFrame', kind: monaco.languages.CompletionItemKind.Class, insertText: 'DataFrame($0)', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: 'pd.DataFrame' },
              { label: 'Series', kind: monaco.languages.CompletionItemKind.Class, insertText: 'Series($0)', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: 'pd.Series' },
              { label: 'concat', kind: monaco.languages.CompletionItemKind.Function, insertText: 'concat([$1], axis=${2:1})', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '拼接 DataFrame/Series' }
            )
          } else if (textUntilPosition.endsWith('np.')) {
            suggestions.push(
              { label: 'array', kind: monaco.languages.CompletionItemKind.Function, insertText: 'array($0)', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '创建数组' },
              { label: 'where', kind: monaco.languages.CompletionItemKind.Function, insertText: 'where($1, $2, $3)', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '条件判断赋值' }
            )
          } else if (textUntilPosition.endsWith('df.') || textUntilPosition.endsWith('self.df.')) {
            suggestions.push(
              { label: 'rolling', kind: monaco.languages.CompletionItemKind.Method, insertText: 'rolling(window=$1).mean()', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '滚动窗口计算' },
              { label: 'shift', kind: monaco.languages.CompletionItemKind.Method, insertText: 'shift(${1:1})', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '序列位移 (滞后)' },
              { label: 'pct_change', kind: monaco.languages.CompletionItemKind.Method, insertText: 'pct_change()', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, detail: '计算收益率' }
            )
          }
          return { suggestions }
        }
      })
      
      return () => { formatProvider.dispose(); completionProvider.dispose() }
    }
  }, [monaco])

  // 💡 监听 AST 语法错误，并在 Monaco 中打上红色波浪线 (Squiggles)
  useEffect(() => {
    if (!monaco || !editorRef.current) return
    const model = editorRef.current.getModel()
    if (model) {
      const markers = syntaxError ? [{
        message: syntaxError.msg, severity: monaco.MarkerSeverity.Error,
        startLineNumber: syntaxError.line || 1, startColumn: 1,
        endLineNumber: syntaxError.line || 1, endColumn: 1000,
      }] : []
      monaco.editor.setModelMarkers(model, 'python', markers)
    }
  }, [monaco, syntaxError])

  // 💡 实时表单热更新 (Auto-Parse): 监听代码变化，防抖 800ms 后静默解析 AST 更新右侧表单
  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        const res = await apiClient.post('/strategy/parse-config', { source_code: store.code })
        if (res.data?.status === 'success' && res.data?.data) {
          store.setFormSchema(res.data.data)
          setSyntaxError(null)
        } else if (res.data?.status === 'error') {
          const match = res.data.message.match(/第 (\d+) 行/)
          const line = match ? parseInt(match[1], 10) : 0
          setSyntaxError({ line, msg: res.data.message })
        }
      } catch (e) {}
    }, 800)
    return () => clearTimeout(timer)
  }, [store.code])

  const handleSyntaxCheck = async () => {
    setIsChecking(true); setSyntaxError(null)
    try {
      const res = await apiClient.post('/strategy/parse-config', { source_code: store.code })
      if (res.data?.status === 'error') {
        const match = res.data.message.match(/第 (\d+) 行/)
        setSyntaxError({ line: match ? parseInt(match[1], 10) : 0, msg: res.data.message })
      } else if (res.data?.data) {
        store.setFormSchema(res.data.data)
        toast({ title: '语法检查通过', description: 'AST 解析成功，动态表单已挂载就绪。' })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally { setIsChecking(false) }
  }

  const handleSaveStrategy = async () => {
    setIsSaving(true)
    const className = store.formSchema.length > 0 ? store.formSchema[0].class_name : 'DraftStrategy'
    const currentCode = editorRef.current ? editorRef.current.getValue() : store.code
    
    try {
      const res = await apiClient.post('/strategy/save', { source_code: currentCode, class_name: className })
      if (res.data?.status === 'success') {
        toast({ title: '✅ 保存成功', description: '策略脚本已成功同步至后端工作区。' })
        if (res.data.data?.formatted_code) {
          const newCode = res.data.data.formatted_code;
          if (editorRef.current && newCode !== editorRef.current.getValue()) {
            const model = editorRef.current.getModel();
            if (model) model.pushEditOperations([], [{ range: model.getFullModelRange(), text: newCode }], () => null);
          } else if (!editorRef.current) {
            store.setCode(newCode)
          }
          store.setLastSavedCode(newCode)
        } else {
          store.setLastSavedCode(currentCode)
        }
        
        store.fetchStrategies()
        store.setActiveStrategy(className)
      } else {
        toast({ variant: 'destructive', title: '保存失败', description: res.data?.message })
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '网络异常', description: e.message })
    } finally { setIsSaving(false) }
  }

  // 💡 Agentic Auto-Debug: 投喂 AST 报错让 AI 自动修复源码
  const handleAutoFix = async () => {
    if (!syntaxError) return
    setIsFixing(true)
    try {
      const fixPrompt = `以下 Python 策略代码在 AST 解析时报语法错误：\n【报错信息】: ${syntaxError.msg}\n\n【错误源码】:\n${store.code}\n\n请直接修复该语法错误，并输出修复后的完整纯 Python 源码。严禁包含任何前言、后语或 Markdown 代码块标记。`
      const assistantMsgId = Date.now().toString()
      store.addMessage({ id: assistantMsgId, role: 'assistant', content: '', reasoning: '', status: 'reasoning' })
      
      const response = await fetch(`${API_BASE_URL}/strategy/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(getAccessToken() ? { 'Authorization': `Bearer ${getAccessToken()}` } : {}) },
        body: JSON.stringify({ prompt: fixPrompt })
      })
      if (!response.body) throw new Error('流式请求发起失败')
      
      const reader = response.body.getReader(); const decoder = new TextDecoder('utf-8'); let done = false; let buffer = ''
      while (!done) {
        const { value, done: readerDone } = await reader.read(); done = readerDone
        if (value) {
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || ''
          for (const line of lines) {
            if (!line.trim()) continue
            try {
              const data = JSON.parse(line)
              if (data.status === 'success') {
                store.setCode(data.data); store.setLastSavedCode(data.data); setSyntaxError(null)
                store.updateMessage(assistantMsgId, { content: '✨ Agent 已经自动修复了 AST 语法错误！', status: 'done' })
                toast({ title: '🔧 AI 自动修复成功', description: 'AST 解析正常。' })
              } else if (data.status === 'error') {
                store.updateMessage(assistantMsgId, { content: `❌ 修复失败: ${data.message}`, status: 'error' })
              }
            } catch (e) { }
          }
        }
      }
    } catch (e: any) { toast({ variant: 'destructive', title: '修复异常', description: e.message }) } finally { setIsFixing(false) }
  }

  return (
    <div className="flex flex-col h-full w-full bg-slate-50 dark:bg-[oklch(0.09_0.005_270)]">
      <div className="flex-1 relative w-full bg-transparent">
        <Editor
          height="100%"
          language="python"
          theme={theme === 'dark' ? 'quant-dark' : 'quant-light'}
          value={store.code}
          onMount={(editor, monaco_instance) => { 
            editorRef.current = editor 
            editor.addCommand(monaco_instance.KeyMod.CtrlCmd | monaco_instance.KeyCode.KeyS, async () => {
              await editor.getAction('editor.action.formatDocument')?.run()
              handleSaveStrategy()
            })
          }}
          onChange={(val) => { store.setCode(val || ''); setSyntaxError(null) }}
          options={{ minimap: { enabled: false }, fontSize: 13, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace', lineHeight: 22, padding: { top: 16, bottom: 16 }, scrollBeyondLastLine: false, smoothScrolling: true, cursorBlinking: "smooth", cursorSmoothCaretAnimation: "on", formatOnPaste: true, overviewRulerLanes: 0, renderLineHighlight: "all", hideCursorInOverviewRuler: true, scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 } }}
          loading={<div className="flex items-center justify-center h-full text-muted-foreground text-xs font-mono gap-2"><Loader2 className="h-4 w-4 animate-spin" /> 启动 Monaco 核心引擎...</div>}
        />
      </div>
      {/* Bottom Action Bar for Editor */}
      <div className="border-t border-border/20 px-4 py-2 flex items-center gap-2 bg-slate-100 dark:bg-[oklch(0.10_0.005_270)] transition-colors duration-300 shrink-0">
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5" onClick={handleSaveStrategy} disabled={isSaving}>
          {isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} {isSaving ? '保存中...' : '保存'}
        </Button>
        {store.isDirty && (<Button size="sm" variant="ghost" onClick={() => store.setCode(store.lastSavedCode)} className="h-7 text-xs px-2 text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-colors animate-in fade-in">放弃修改</Button>)}
        <Button size="sm" variant="outline" onClick={handleSyntaxCheck} disabled={isChecking} className="h-7 text-xs gap-1.5 transition-colors">
          {isChecking ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />} 强制语法检查
        </Button>
        {syntaxError ? (
          <div className="ml-auto flex items-center gap-2 animate-in fade-in zoom-in duration-300">
            <span className="text-[10px] font-mono text-red-500 flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5" /> {syntaxError.msg}</span>
            <Button size="sm" onClick={handleAutoFix} disabled={isFixing} className="h-6 px-2 text-[10px] bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 hover:bg-red-500/20 shadow-none gap-1">{isFixing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />} {isFixing ? '修复中...' : 'AI 一键修复'}</Button>
          </div>
        ) : store.formSchema.length > 0 ? (<span className="ml-auto text-[10px] font-mono text-emerald-600 dark:text-emerald-400 animate-in fade-in zoom-in duration-300">✓ AST 解析正常</span>) : null}
      </div>
    </div>
  )
}