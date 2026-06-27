import React, { useState } from 'react';
import { Bot, Loader2, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api-client';
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
      return <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-500/90 text-[11px] font-mono whitespace-pre-wrap break-words shadow-inner"><div className="font-bold mb-2 flex items-center gap-1.5">⚠️ 渲染异常降级保护 (Render Fallback)</div>{this.props.fallbackContent}</div>;
    }
    return this.props.children;
  }
}

export function ScreenerAISummary({ results }: { results: any[] }) {
  const [summary, setSummary] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);

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

  return (
    <div className="mb-4 animate-in fade-in slide-in-from-bottom-2">
      {!summary && !isGenerating ? (
        <Button 
          onClick={handleSummarize} 
          variant="outline" 
          className="w-full flex items-center gap-2 h-10 border-indigo-500/30 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/10 transition-all shadow-sm"
        >
          <Sparkles className="w-4 h-4" />
          ✨ AI 一键洞察当前结果 (提炼主线概念并点评龙头股)
        </Button>
      ) : (
        <div className="glass-card rounded-xl border border-indigo-500/30 shadow-sm bg-indigo-500/5 overflow-hidden transition-all duration-300">
          <div 
            className="px-4 py-2.5 border-b border-indigo-500/20 bg-indigo-500/10 flex items-center justify-between cursor-pointer hover:bg-indigo-500/15 transition-colors"
            onClick={() => setIsExpanded(!isExpanded)}
          >
            <div className="flex items-center gap-2">
              <Bot className={`w-4 h-4 text-indigo-500 ${isGenerating ? 'animate-pulse' : ''}`} />
              <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400">
                {isGenerating ? 'DeepSeek 正在扫描新闻并推演盘面洞察...' : 'AI 选股结果洞察报告'}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {!isGenerating && summary && (
                <button 
                  onClick={(e) => { e.stopPropagation(); handleSummarize(); }} 
                  className="text-[10px] text-indigo-500 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                >
                  重新生成
                </button>
              )}
              {isExpanded ? <ChevronUp className="w-4 h-4 text-indigo-500" /> : <ChevronDown className="w-4 h-4 text-indigo-500" />}
            </div>
          </div>
          
          {isExpanded && (
            <div className="p-4 text-sm text-foreground/90 whitespace-pre-wrap leading-relaxed markdown-body">
              {isGenerating ? (
                <div className="flex flex-col items-center justify-center py-6 gap-3">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  <span className="text-xs text-muted-foreground font-mono">正在并发拉取 Top 10 标的最新新闻与走势...</span>
                </div>
              ) : (
                <SummaryErrorBoundary fallbackContent={safeSummary}>
                  <ReactMarkdown>{safeSummary}</ReactMarkdown>
                </SummaryErrorBoundary>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
