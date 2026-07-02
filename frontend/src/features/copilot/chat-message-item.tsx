import React, { useRef, useState, useEffect, useCallback } from 'react'
import { User, Bot, Loader2, Sparkles, ChevronRight, ChevronDown, ChevronUp, Search, Globe, Database, FileText, Code2, Check, Copy, RotateCcw, AlertTriangle, Rocket } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ThinkTimer } from '@/features/copilot/think-timer'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { EChartsRenderer } from '@/features/copilot/echarts-renderer'
import { MermaidRenderer } from '@/features/copilot/mermaid-renderer'
import { ChatMessage } from './types'
import { useNavigate } from 'react-router-dom'
import { useTheme } from 'next-themes'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus, vs } from 'react-syntax-highlighter/dist/esm/styles/prism'

const CodeBlockRenderer = React.memo(({ codeContent, isStrategyCode, lang, children, codeProps, navigate, isGenerating }: any) => {
  const [copied, setCopied] = useState(false);
  // 💡 初始加载时：如果代码大于 50 行且不在生成状态（如查看历史记录），默认折叠
  const [isCollapsed, setIsCollapsed] = useState(() => codeContent.split('\n').length > 50 && !isGenerating);
  const [prevGenerating, setPrevGenerating] = useState(isGenerating);
  const { theme } = useTheme();

  // 💡 监听生成结束事件：当 AI 输出完毕时，若代码过长则瞬间自动折叠
  useEffect(() => {
    if (prevGenerating && !isGenerating && codeContent.split('\n').length > 50) {
      setIsCollapsed(true);
    }
    setPrevGenerating(isGenerating);
  }, [isGenerating, codeContent, prevGenerating]);

  return (
    <div className="relative my-3 rounded-lg overflow-hidden border border-border/50 bg-slate-50 dark:bg-[#1e1e1e] shadow-sm">
      <div className="bg-secondary/40 text-muted-foreground text-[10px] px-3 py-1 font-mono border-b border-border/50 uppercase flex items-center justify-between">
        <span>{lang}</span>
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex items-center justify-center p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
          title={isCollapsed ? "展开代码" : "收起代码"}
        >
          {isCollapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
        </button>
      </div>
      
      {!isCollapsed && (
        <>
          <div className="overflow-x-auto custom-scrollbar text-[11px] leading-relaxed">
            <SyntaxHighlighter 
              language={lang || 'text'} 
              style={theme === 'dark' ? vscDarkPlus : vs} 
              customStyle={{ margin: 0, padding: '12px', background: 'transparent' }} 
              PreTag="div"
            >
              {String(codeContent).replace(/\n$/, '')}
            </SyntaxHighlighter>
          </div>
          {/* 💡 将操作按钮统一下沉至底部工具栏 */}
          <div className="flex items-center justify-end gap-2 bg-secondary/20 border-t border-border/40 px-2 py-1.5">
            <button
              onClick={() => {
                navigator.clipboard.writeText(codeContent);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors px-1.5 py-0.5 rounded hover:bg-secondary/60"
            >
              {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
              <span className={copied ? "text-emerald-500" : ""}>{copied ? '已复制' : '复制代码'}</span>
            </button>
            {isStrategyCode && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  sessionStorage.setItem('quant_strategy_initial_code', codeContent);
                  window.dispatchEvent(new CustomEvent('quant_strategy_code_invoke', { detail: { code: codeContent } }));
                  
                  setTimeout(() => {
                    const tabTrigger = document.querySelector('[role="tab"][value="strategy"], [data-value="strategy"], a[href="/strategy"], a[href="#strategy"]') as HTMLElement;
                    if (tabTrigger) { tabTrigger.click(); }
                    else if (navigate) { navigate('/strategy'); }
                    else { window.location.href = '/strategy'; }
                  }, 50);
                }}
                className="flex items-center gap-1.5 hover:text-indigo-400 text-indigo-500 transition-colors bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 normal-case"
                title="将此代码发送至工作台，一键生成实盘策略"
              >
                <Code2 className="h-3 w-3" />
                转为策略
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
})

class MarkdownErrorBoundary extends React.Component<{children: React.ReactNode, fallbackContent: string}, {hasError: boolean, error: any}> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: any) {
    return { hasError: true, error };
  }
  componentDidCatch(error: any, errorInfo: any) {
    console.error("Markdown 渲染崩溃拦截:", error, errorInfo);
  }
  componentDidUpdate(prevProps: any) {
    // 💡 流式恢复机制：如果大模型的新 Chunk 到达，可能修复了之前残缺的语法树，重置错误状态以尝试重新渲染高亮
    if (this.state.hasError && prevProps.fallbackContent !== this.props.fallbackContent) {
      this.setState({ hasError: false, error: null });
    }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-500/90 text-[11px] font-mono whitespace-pre-wrap break-words shadow-inner">
          <div className="font-bold mb-2 flex items-center gap-1.5 text-red-500"><AlertTriangle className="h-3.5 w-3.5"/> 渲染异常降级保护 (Render Fallback)</div>
          {this.props.fallbackContent}
        </div>
      );
    }
    return this.props.children;
  }
}

export const ChatMessageItem = React.memo(({
  msg,
  idx,
  isLast,
  isGenerating,
  copiedIndex,
  onCopy,
  onRetry,
  onSend
}: {
  msg: ChatMessage;
  idx: number;
  isLast: boolean;
  isGenerating: boolean;
  copiedIndex: number | null;
  onCopy: (text: string, idx: number) => void;
  onRetry: (idx: number) => void;
  onSend: (text: string) => void;
}) => {
  // 获取 React Router 实例，用于跨页面/模块平滑跳转
  const navigate = useNavigate();

  const content = msg.content || ''
  let thinkContent = ''
  let finalContent = content

  const thinkStart = content.indexOf('<think>')
  const thinkEnd = content.indexOf('</think>')

  if (thinkStart !== -1) {
    if (thinkEnd !== -1) {
      thinkContent = content.substring(thinkStart + 7, thinkEnd).trim()
      finalContent = (content.substring(0, thinkStart) + content.substring(thinkEnd + 8)).trim()
    } else {
      thinkContent = content.substring(thinkStart + 7).trim()
      finalContent = content.substring(0, thinkStart).trim()
    }
  }

  // 💡 第一层防御：智能补全未闭合的代码块标签，防止渲染器或高亮插件由于格式残缺导致崩溃
  // 仅匹配作为代码块边界的 ```（通常在行首），防止误伤普通文本中的反引号
  const codeBlockMatches = finalContent.match(/(?:^|\n)\s*```/g);
  if (codeBlockMatches && codeBlockMatches.length % 2 !== 0) {
    finalContent += '\n\n```';
  }

  const hasTools = msg.tools && msg.tools.length > 0;
  const hasThinking = !!thinkContent;
  const isThinkingState = isGenerating && isLast && thinkStart !== -1 && thinkEnd === -1;
  const hasRunningTools = msg.tools?.some(t => t.status === 'running');
  const isExpanded = isThinkingState || hasRunningTools;
  
  // 💡 针对深度思考内容过长导致的页面伸缩跳动，为其设置独立滚动条，并在生成时自动将其内部滚动到底部
  const thinkContentRef = useRef<HTMLDivElement>(null)
  const thinkUserScrolledRef = useRef(false)

  useEffect(() => {
    // 💡 如果用户手动向上滚动了，则停止自动追踪底部
    if (isThinkingState && thinkContentRef.current && !thinkUserScrolledRef.current) {
      thinkContentRef.current.scrollTop = thinkContentRef.current.scrollHeight
    }
  }, [thinkContent, isThinkingState])

  const handleThinkScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget
    const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 50
    thinkUserScrolledRef.current = !isAtBottom
  }, [])

  return (
    <div 
      className={cn("flex gap-4 max-w-4xl mx-auto w-full animate-in slide-in-from-bottom-2 fade-in duration-300", msg.role === 'user' ? "flex-row-reverse" : "flex-row")}
      style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 200px' }} // 💡 开启浏览器级原生虚拟滚动，防止长列表重绘卡顿
    >
      <div className={cn("h-8 w-8 rounded-lg shrink-0 flex items-center justify-center border shadow-sm mt-1", msg.role === 'user' ? "bg-primary/20 border-primary/30 text-primary" : "bg-emerald-500/20 border-emerald-500/30 text-emerald-400")}>
        {msg.role === 'user' ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={cn("px-5 py-4 rounded-2xl text-sm leading-relaxed", msg.role === 'user' ? "bg-primary/10 border border-primary/20 text-foreground rounded-tr-sm shadow-sm" : "bg-card border border-border/40 text-foreground rounded-tl-sm shadow-sm dark:shadow-[0_0_15px_rgba(0,0,0,0.5)]", msg.role === 'assistant' && "min-w-[280px] max-w-full overflow-hidden")}>
        
        {msg.role === 'user' ? (
          <div className="flex flex-col gap-2">
            <div className="whitespace-pre-wrap font-mono">{msg.content}</div>
            {msg.attachments && msg.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-1">
                {msg.attachments.map((att, i) => (
                  <div key={i} className="flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 p-1.5 rounded-lg max-w-xs">
                    {att.type.startsWith('image/') ? (
                      <img src={att.url} alt={att.name} className="h-10 w-10 object-cover rounded shadow-sm border border-indigo-500/20" />
                    ) : (
                      <div className="h-10 w-10 flex items-center justify-center bg-indigo-500/20 rounded border border-indigo-500/30">
                        <FileText className="h-5 w-5 text-indigo-500" />
                      </div>
                    )}
                    <span className="text-[10px] text-indigo-700 dark:text-indigo-300 truncate font-semibold px-1">{att.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col">
            {(hasThinking || hasTools) && (
              <details 
                className="group border border-border/30 rounded-lg overflow-hidden bg-slate-50/50 dark:bg-black/20 text-xs transition-colors mb-3" 
                open={isExpanded}
              >
                <summary className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-100 dark:hover:bg-white/5 font-semibold select-none list-none transition-colors [&::-webkit-details-marker]:hidden">
                  {(isThinkingState || hasRunningTools) ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : <Sparkles className="h-3.5 w-3.5 text-slate-500" />}
                  <span className="text-slate-600 dark:text-gray-300">思考过程</span>
                  {msg.startTime && (
                    <span className="text-[10px] text-muted-foreground ml-1">
                      (<ThinkTimer startTime={msg.startTime} endTime={msg.thinkEndTime} />)
                    </span>
                  )}
                  <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground transition-transform duration-200 group-open:rotate-90" />
                </summary>
                <div 
                  ref={thinkContentRef} 
                  onScroll={handleThinkScroll}
                  className="px-3 pb-3 pt-2 border-t border-border/20 text-muted-foreground whitespace-pre-wrap break-all bg-white dark:bg-black/40 max-h-96 overflow-y-auto custom-scrollbar"
                >
                  {hasThinking && (
                    <div className="italic text-slate-500 dark:text-slate-400 mb-3 last:mb-0">
                      {thinkContent}
                    </div>
                  )}
                  {hasTools && (
                    <div className="flex flex-col gap-2">
                      {msg.tools!.map((tool, tIdx) => {
                        const tName = tool.name.toLowerCase();
                        const isSearch = tName.includes('search');
                        const isNews = tName.includes('news');
                        const isMarket = tName.includes('market') || tName.includes('quote');
                        const isBrowse = tName.includes('browse') || tName.includes('read');
                        const ToolIcon = isSearch ? Search : isNews ? Globe : isMarket ? Database : isBrowse ? FileText : Code2;
                        
                        let actionName = '调用工具';
                        if (isSearch) actionName = '搜索网络';
                        else if (isNews) actionName = '检索资讯';
                        else if (isMarket) actionName = '获取行情';
                        else if (isBrowse) actionName = '阅读网页';

                        let queryDesc = tool.input;
                        try {
                          const parsed = JSON.parse(tool.input);
                          const key = ['query', 'q', 'ticker', 'keyword', 'url'].find(k => parsed[k]);
                          if (key && typeof parsed[key] === 'string') queryDesc = parsed[key];
                        } catch(e) { /* ignore parse error */ }

                        let resultList: any[] | null = null;
                        try {
                          if (tool.result) {
                            const parsed = JSON.parse(tool.result);
                            if (Array.isArray(parsed)) resultList = parsed;
                            else if (parsed && Array.isArray(parsed.data)) resultList = parsed.data;
                            else if (parsed && Array.isArray(parsed.results)) resultList = parsed.results;
                          }
                        } catch(e) { /* ignore parse error */ }

                        return (
                          <div key={tIdx} className="border border-border/30 rounded-md p-2 bg-slate-100/50 dark:bg-zinc-900/50">
                            <div className="flex items-center gap-1.5 mb-1 text-[11px] font-bold text-slate-700 dark:text-slate-300">
                              {tool.status === 'running' ? <Loader2 className="h-3 w-3 animate-spin text-primary" /> : <ToolIcon className="h-3 w-3 text-emerald-500" />}
                              {actionName} {tool.name !== actionName && <span className="font-mono text-[9px] text-muted-foreground">({tool.name})</span>}
                              {queryDesc && queryDesc !== '{}' && <span className="text-muted-foreground font-normal truncate max-w-[200px]"> - {queryDesc}</span>}
                            </div>
                            
                            {tool.status === 'done' && (
                              <div className="mt-1.5 pt-1.5 border-t border-border/40">
                                {resultList ? (
                                  <div className="text-[10px] text-muted-foreground mb-1 font-medium">
                                    ✅ {isBrowse ? '浏览了' : '获取到'} {resultList.length} {isBrowse ? '个页面' : isNews ? '篇资讯' : '条数据'}
                                  </div>
                                ) : (
                                  <div className="text-[10px] text-muted-foreground mb-1 font-medium">
                                    ✅ 执行完毕
                                  </div>
                                )}
                                
                                <details className="group/tool mt-1">
                                  <summary className="text-[10px] text-slate-500 cursor-pointer hover:text-primary transition-colors flex items-center gap-1 w-fit select-none">
                                    查看详细内容 <ChevronRight className="h-3 w-3 transition-transform group-open/tool:rotate-90" />
                                  </summary>
                                  <div className="mt-2 max-h-40 overflow-y-auto custom-scrollbar bg-white dark:bg-black/40 p-1.5 rounded border border-border/50">
                                    {resultList && resultList.length > 0 && (resultList[0].title || resultList[0].headline || resultList[0].name) ? (
                                      <div className="flex flex-col gap-1.5">
                                        {resultList.map((item, i) => {
                                          const title = item.title || item.headline || item.name;
                                          const url = item.url || item.link;
                                          const sentiment = item.sentiment;
                                          
                                          if (sentiment) {
                                            const isBullish = sentiment.label === 'Bullish';
                                            const isBearish = sentiment.label === 'Bearish';
                                            const tagColor = isBullish ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' : 
                                                             isBearish ? 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20' : 
                                                             'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
                                            
                                            return (
                                              <div key={i} className="border border-border/50 rounded flex flex-col p-2 bg-slate-50 dark:bg-black/30 hover:bg-slate-100 dark:hover:bg-black/50 transition-colors">
                                                <div className="flex items-start justify-between gap-2 mb-1">
                                                  <div className="font-semibold text-[11px] text-foreground line-clamp-1" title={sentiment.summary_zh || title}>
                                                    {url ? <a href={url} target="_blank" className="hover:underline">{sentiment.summary_zh || title}</a> : (sentiment.summary_zh || title)}
                                                  </div>
                                                  <div className={cn("text-[9px] px-1.5 py-0.5 rounded border whitespace-nowrap flex items-center gap-1 font-mono", tagColor)}>
                                                    {isBullish ? '🟢' : isBearish ? '🔴' : '⚪'} {sentiment.label} ({sentiment.score})
                                                  </div>
                                                </div>
                                                <div className="text-[10px] text-muted-foreground line-clamp-1 mb-1.5" title={title}>
                                                  {title}
                                                </div>
                                                <div className="text-[10px] text-slate-600 dark:text-slate-400 bg-secondary/40 px-2 py-1.5 rounded-sm border border-border/30 line-clamp-2" title={sentiment.reasoning}>
                                                  <span className="font-bold">💡 研判: </span>{sentiment.reasoning}
                                                </div>
                                              </div>
                                            )
                                          }

                                          return (
                                            <div key={i} className="text-[10px] text-slate-600 dark:text-gray-400 line-clamp-1 flex items-center gap-1.5 before:content-['•'] before:text-slate-400 px-1">
                                              {url ? <a href={url} target="_blank" className="hover:text-primary hover:underline" title={title}>{title}</a> : <span title={title}>{title}</span>}
                                            </div>
                                          )
                                        })}
                                      </div>
                                    ) : (
                                      <code className="text-[10px] font-mono text-slate-600 dark:text-gray-400 whitespace-pre-wrap break-all">{tool.result || '无数据返回'}</code>
                                    )}
                                  </div>
                                </details>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </details>
            )}

            <div className="markdown-body">
              <MarkdownErrorBoundary fallbackContent={finalContent}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[[rehypeKatex, { strict: false }]]}
                  components={{
                    p: ({node, ...props}) => <div className="mb-2 last:mb-0 leading-relaxed" {...props} />,
                    a: ({node, ...props}) => <a className="text-emerald-500 hover:text-emerald-400 hover:underline underline-offset-4" target="_blank" rel="noreferrer" {...props} />,
                    h1: ({node, ...props}) => <h1 className="text-lg font-bold mt-4 mb-2 text-foreground" {...props} />,
                    h2: ({node, ...props}) => <h2 className="text-base font-bold mt-3 mb-2 text-foreground" {...props} />,
                    h3: ({node, ...props}) => <h3 className="text-sm font-bold mt-2 mb-1 text-foreground" {...props} />,
                    ul: ({node, ...props}) => <ul className="list-disc list-outside ml-4 mb-2 space-y-1" {...props} />,
                    ol: ({node, ...props}) => <ol className="list-decimal list-outside ml-4 mb-2 space-y-1" {...props} />,
                    li: ({node, ...props}: any) => {
                      const extractText = (children: any): string => {
                        let text = ''
                        React.Children.forEach(children, child => {
                          if (typeof child === 'string') text += child
                          else if (React.isValidElement(child) && (child.props as any).children) text += extractText((child.props as any).children)
                        })
                        return text
                      }
                      const fullText = extractText(props.children).trim()
                      const match = fullText.match(/^["“「](.+?)["”」]$/)
                      
                      if (match) {
                        const cmd = match[1]
                        return (
                          <li className="list-none inline-block mr-2 mt-1 mb-1 -ml-4">
                            <button onClick={() => onSend(cmd)} disabled={isGenerating} className="px-3 py-1.5 rounded-full bg-indigo-500/10 text-indigo-400 text-xs border border-indigo-500/20 hover:bg-indigo-500/20 hover:text-indigo-300 hover:shadow-[0_0_10px_rgba(99,102,241,0.2)] transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed" title="点击快捷发送">
                              <Sparkles className="w-3 h-3" /> {cmd}
                            </button>
                          </li>
                        )
                      }
                      return <li className="pl-1" {...props} />
                    },
                    blockquote: ({node, ...props}) => <blockquote className="border-l-2 border-primary/50 pl-3 py-1.5 my-2 bg-primary/5 text-muted-foreground italic rounded-r-md" {...props} />,
                    code: ({node, inline, className, children, ...props}: any) => {
                      const match = /language-(\w+)/.exec(className || '')
                      const lang = match ? match[1].toLowerCase() : ''
                      
                      const codeContent = String(children)
                      const isInline = typeof inline === 'boolean' ? inline : !match && !codeContent.includes('\n')
                      
                      // 💡 精准识别策略与特征提取代码：包含函数、类、数据科学库的较长代码才会显示转为策略按钮
                      const isStrategyCode = (lang === 'python' || !match) && (
                        codeContent.includes('def ') || 
                        codeContent.includes('class ') || 
                        codeContent.includes('import ') || 
                        codeContent.includes('pd.') || 
                        codeContent.includes('np.')
                      ) && codeContent.split('\n').length > 3;
  
                      if (!isInline && lang === 'echarts') {
                        try {
                          const jsonObj = JSON.parse(String(children))
                          return (
                            <div className="my-4 rounded-xl border border-border/40 bg-zinc-950/50 p-2 shadow-lg overflow-hidden">
                              <div className="px-2 pt-2 pb-1 text-[10px] text-emerald-400/80 font-bold uppercase tracking-widest flex items-center gap-1.5 border-b border-border/20 mb-2">
                                <Sparkles className="w-3 h-3" /> 数据可视化研判 (Data Visualization)
                              </div>
                              <EChartsRenderer options={jsonObj} />
                            </div>
                          )
                        } catch (err) {
                          return <div className="my-4 p-3 rounded-lg border border-red-500/20 bg-red-500/10 text-xs text-red-400 font-mono">⚠️ 动态图表解析中，等待 JSON 格式闭环...</div>
                        }
                      }
  
                      if (!isInline && lang === 'mermaid') {
                        return <MermaidRenderer chart={String(children)} />
                      }
                      
                      return !isInline ? (
                        <CodeBlockRenderer 
                          codeContent={codeContent} 
                          isStrategyCode={isStrategyCode} 
                          lang={match ? match[1] : 'code'} 
                          codeProps={props}
                          navigate={navigate}
                          isGenerating={isGenerating}
                        >
                          {children}
                        </CodeBlockRenderer>
                      ) : (
                        <code className="bg-secondary/60 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded text-[11px] font-mono mx-0.5" {...props}>{children}</code>
                      )
                    },
                    table: ({node, ...props}) => <div className="overflow-x-auto my-3 custom-scrollbar rounded-lg border border-border/40 bg-slate-50 dark:bg-secondary/10 shadow-sm"><table className="w-full text-left border-collapse text-xs" {...props} /></div>,
                    thead: ({node, ...props}) => <thead className="bg-slate-100 dark:bg-secondary/40 border-b border-border/40" {...props} />,
                    tr: ({node, ...props}) => <tr className="hover:bg-slate-200/50 dark:hover:bg-secondary/30 transition-colors group" {...props} />,
                    th: ({node, ...props}) => <th className="px-3 py-2 font-semibold text-foreground whitespace-nowrap border-b border-border/20" {...props} />,
                    td: ({node, ...props}) => <td className="px-3 py-2 border-b border-border/10 text-muted-foreground group-hover:text-foreground transition-colors" {...props} />,
                    hr: ({node, ...props}) => <hr className="my-4 border-border/30" {...props} />
                  }}
                >
                  {finalContent}
                </ReactMarkdown>
              </MarkdownErrorBoundary>
              
              {/* 💡 策略部署卡片：渲染后端标记的策略代码块，附带一键部署按钮 */}
              {msg.strategyBlocks && msg.strategyBlocks.length > 0 && (
                <div className="mt-4 space-y-3">
                  {msg.strategyBlocks.map((block, bIdx) => (
                    <div key={bIdx} className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-500/10 overflow-hidden shadow-sm">
                      <div className="flex items-center justify-between px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-500/20">
                        <div className="flex items-center gap-2">
                          <Rocket className="h-4 w-4 text-emerald-500" />
                          <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">策略代码 (Strategy Block)</span>
                          <span className="text-[10px] text-muted-foreground font-mono">{block.code.split('\n').length} 行</span>
                        </div>
                        <button
                          onClick={() => {
                            sessionStorage.setItem('quant_strategy_initial_code', block.code)
                            window.dispatchEvent(new CustomEvent('quant_strategy_code_invoke', { detail: { code: block.code } }))
                            const tabTrigger = document.querySelector('[role="tab"][value="strategy"], [data-value="strategy"], a[href="/strategy"], a[href="#strategy"]') as HTMLElement
                            if (tabTrigger) { tabTrigger.click() }
                            else if (navigate) { navigate('/strategy') }
                            else { window.location.href = '/strategy' }
                          }}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-bold shadow-sm hover:shadow-md transition-all"
                        >
                          <Rocket className="h-3 w-3" />
                          一键部署
                        </button>
                      </div>
                      <div className="overflow-x-auto custom-scrollbar text-[11px] leading-relaxed max-h-64">
                        <pre className="p-3 font-mono text-slate-700 dark:text-slate-300 whitespace-pre">{block.code}</pre>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              
              {isGenerating && isLast && !isThinkingState && (
                <span className="inline-block w-1.5 h-4 mt-2 align-middle bg-emerald-400 animate-pulse" />
              )}
              
              {!isThinkingState && (finalContent || !isGenerating) && (
                <div className="flex items-center gap-2 mt-4 pt-3 border-t border-border/30 text-muted-foreground select-none">
                  <button 
                    onClick={() => onCopy(finalContent, idx)} 
                    className="flex items-center gap-1.5 text-[10px] hover:text-foreground transition-colors px-1.5 py-1 rounded-md hover:bg-secondary/60" 
                    title="复制内容"
                  >
                    {copiedIndex === idx ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                    <span>{copiedIndex === idx ? '已复制' : '复制'}</span>
                  </button>
                  {isLast && (
                    <button 
                      onClick={() => onRetry(idx)} 
                      disabled={isGenerating} 
                      className="flex items-center gap-1.5 text-[10px] hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed px-1.5 py-1 rounded-md hover:bg-secondary/60" 
                      title="重新生成"
                    >
                      <RotateCcw className={cn("h-3 w-3", isGenerating && "animate-spin")} />
                      <span>重试</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}, (prev, next) => {
  return (
    prev.msg === next.msg &&
    prev.isLast === next.isLast &&
    prev.isGenerating === next.isGenerating &&
    prev.copiedIndex === next.copiedIndex
  )
})