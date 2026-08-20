import React, { useState } from 'react';
import { Bot, Loader2, Sparkles, ChevronDown, ChevronUp, AlertTriangle, Lightbulb, Star } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api-client';
import { formatDisplaySymbol } from './shared';
import ReactMarkdown from 'react-markdown';

// 💡 React 错误边界：捕获 Markdown 渲染器内部崩溃，防止整个页面白屏
class SummaryErrorBoundary extends React.Component<{children: React.ReactNode, fallbackContent: string}, {hasError: boolean}> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidUpdate(prevProps: any) {
    // 当大模型重新生成并下发新文本时，重置错误状态以尝试重新渲染
    if (this.state.hasError && prevProps.fallbackContent !== this.props.fallbackContent) {
      this.setState({ hasError: false });
    }
  }
  render() {
    if (this.state.hasError) {
      return <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-600 dark:text-amber-500 text-[11px] font-mono whitespace-pre-wrap break-words shadow-inner"><div className="font-bold mb-2 flex items-center gap-1.5">⚠️ 渲染异常降级保护 (Render Fallback)</div>{this.props.fallbackContent}</div>;
    }
    return this.props.children;
  }
}

// 设计稿 AI 解读卡三维度：关键逻辑 / 风险提示 / 推荐清单
const DIMENSIONS = [
  { id: 'logic', label: '关键逻辑', icon: Lightbulb },
  { id: 'risk', label: '风险提示', icon: AlertTriangle },
  { id: 'pick', label: '推荐清单', icon: Star },
] as const

export function ScreenerAISummary({ results }: { results: any[] }) {
  const [summary, setSummary] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  const [activeDim, setActiveDim] = useState<typeof DIMENSIONS[number]['id']>('logic');

  const handleSummarize = async () => {
    if (!results || results.length === 0) return;
    setIsGenerating(true);
    setSummary('');
    setIsExpanded(true);

    try {
      // 发送前 10 只股票给后端 (后端自带截断保护)
      const topStocks = results.slice(0, 10);
      const res = await apiClient.post('/screener/summarize', { stocks: topStocks });

      if (res.data?.status === 'success') {
        setSummary(res.data.data);
      } else {
        setSummary(`❌ 生成失败: ${res.data?.message}`);
      }
    } catch (e: any) {
      setSummary(`❌ 网络异常: ${e.message}`);
    } finally {
      setIsGenerating(false);
    }
  };

  // 如果没有筛选结果，不展示该按钮
  if (!results || results.length === 0) return null;

  // 💡 第一层防御：智能补全未闭合的代码块标签，防止渲染器或高亮插件由于格式残缺导致崩溃
  let safeSummary = summary;
  const codeBlockMatches = safeSummary.match(/(?:^|\n)\s*```/g);
  if (codeBlockMatches && codeBlockMatches.length % 2 !== 0) {
    safeSummary += '\n\n```';
  }

  const topPicks = results.slice(0, 5);

  return (
    <div className="animate-in fade-in slide-in-from-bottom-2">
      {!summary && !isGenerating ? (
        <Button
          onClick={handleSummarize}
          variant="outline"
          className="w-full flex items-center gap-2 h-10 border-primary/30 text-primary hover:bg-primary/10 transition-all shadow-sm"
        >
          <Sparkles className="w-4 h-4" />
          ✨ AI 一键解读当前选股结果（关键逻辑 / 风险提示 / 推荐清单）
        </Button>
      ) : (
        <div className="glass-card rounded-[var(--radius-card)] border border-primary/20 shadow-sm bg-primary/[0.03] overflow-hidden transition-all duration-300">
          <div
            className="px-4 py-2.5 border-b border-primary/15 bg-primary/[0.06] flex items-center justify-between cursor-pointer hover:bg-primary/10 transition-colors"
            onClick={() => setIsExpanded(!isExpanded)}
          >
            <div className="flex items-center gap-2">
              <Bot className={cn('w-4 h-4 text-primary', isGenerating && 'animate-pulse')} />
              <span className="text-xs font-bold text-primary">
                {isGenerating ? 'DeepSeek 正在扫描新闻并推演盘面洞察...' : 'AI 选股结果解读'}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {!isGenerating && summary && (
                <button
                  onClick={(e) => { e.stopPropagation(); handleSummarize(); }}
                  className="text-[10px] text-primary/80 hover:text-primary transition-colors"
                >
                  重新生成
                </button>
              )}
              {isExpanded ? <ChevronUp className="w-4 h-4 text-primary" /> : <ChevronDown className="w-4 h-4 text-primary" />}
            </div>
          </div>

          {isExpanded && (
            <div>
              {/* 三维解读切换标签 */}
              <div className="flex items-center gap-1 px-3 pt-2.5 border-b border-border/30">
                {DIMENSIONS.map((d) => {
                  const Icon = d.icon
                  return (
                    <button
                      key={d.id}
                      onClick={() => setActiveDim(d.id)}
                      className={cn('flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium rounded-t-md transition-colors border-b-2', activeDim === d.id ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground')}
                    >
                      <Icon className="w-3 h-3" /> {d.label}
                    </button>
                  )
                })}
              </div>

              <div className="p-4 text-sm text-foreground/90 whitespace-pre-wrap leading-relaxed markdown-body min-h-[80px]">
                {isGenerating ? (
                  <div className="flex flex-col items-center justify-center py-6 gap-3">
                    <Loader2 className="w-6 h-6 animate-spin text-primary" />
                    <span className="text-xs text-muted-foreground font-mono">正在并发拉取 Top 10 标的最新新闻与走势...</span>
                  </div>
                ) : activeDim === 'pick' ? (
                  <div className="flex flex-wrap gap-2">
                    {topPicks.length === 0 ? <span className="text-xs text-muted-foreground">暂无标的</span> : topPicks.map((s: any) => {
                      const chg = Number(s.chg) || 0
                      const trend = chg > 0 ? 'text-red-500' : chg < 0 ? 'text-emerald-400' : 'text-foreground'
                      return (
                        <span key={s.symbol} className="inline-flex flex-col items-start px-2.5 py-1.5 rounded-lg bg-secondary/60 border border-border/40 font-mono">
                          <span className="text-[11px] text-foreground font-medium">{formatDisplaySymbol(s.symbol)}</span>
                          <span className={cn('text-[10px] tabular-nums', trend)}>{chg > 0 ? '+' : ''}{chg.toFixed(2)}%</span>
                        </span>
                      )
                    })}
                  </div>
                ) : (
                  <SummaryErrorBoundary fallbackContent={safeSummary}>
                    <ReactMarkdown>{safeSummary}</ReactMarkdown>
                  </SummaryErrorBoundary>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
