import React from 'react';
import { Newspaper } from 'lucide-react';
import { cn } from '@/lib/utils';
import { HighlightedText, NEWS_TAG_COLORS } from './shared';
import { useI18n, type DictionaryKey } from '@/contexts/i18n';
import { useTheme } from 'next-themes';

export function NewsStream({ news, visibleNewsCount, setVisibleNewsCount }: { news: any[], visibleNewsCount: number, setVisibleNewsCount: React.Dispatch<React.SetStateAction<number>> }) {
  const { t } = useI18n();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px]">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 flex-shrink-0">
        <Newspaper className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">LLM 情感打分 · 财经快讯</span>
        <span className="ml-auto text-[10px] text-muted-foreground font-mono">
          {news.length > 0 ? `共 ${news.length} 条` : ''}
        </span>
      </div>
      <div className="flex-1 divide-y divide-border/15 overflow-y-auto custom-scrollbar">
        {news.slice(0, visibleNewsCount).map((n: any, i: number) => {
          const titleText = n.title || n.headline || '未知';
          let ts = n.time;
          if (!ts && n.datetime) ts = new Date(n.datetime * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
          ts = ts || '最近';
          
          const sentimentObj = typeof n.sentiment === 'object' ? n.sentiment : null;
          const score = sentimentObj ? Number(sentimentObj.score) : 0;
          const label = sentimentObj?.label || (score >= 0 ? 'Bullish' : 'Bearish');
          const reasoning = sentimentObj?.reasoning || '';
          const summaryZh = sentimentObj?.summary_zh || '';
          const bullish = score >= 0;
          const it = Math.min(Math.abs(score) / 100, 1);

          return (
            <div key={n.headline || i} className="animate-news-item" style={{ animationDelay: `${i * 50}ms` }}>
              <div className="overflow-hidden">
                <div className="px-4 py-3 flex flex-col gap-2 hover:bg-slate-50 dark:hover:bg-secondary/20 transition-colors">
                  <div className="flex items-center gap-4">
                    <div className="flex-shrink-0 w-1 self-stretch rounded-full" style={{ background: bullish ? `rgba(${isDark ? '14,203,129' : '5,150,105'},${it || 0.1})` : `rgba(${isDark ? '246,70,93' : '225,29,72'},${it || 0.1})` }} />
                    <div className="flex-1 min-w-0">
                      <a href={n.url || '#'} target={n.url ? '_blank' : '_self'} rel="noreferrer" className="text-xs font-medium leading-snug hover:text-primary transition-colors cursor-pointer line-clamp-2">
                        <HighlightedText text={titleText} />
                      </a>
                      {n.tags && n.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {n.tags.map((tg: string) => {
                            const colorCls = NEWS_TAG_COLORS[tg.toUpperCase()] || 'bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/30';
                            return <span key={tg} className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded-md border whitespace-nowrap', colorCls)}>{t(tg.toUpperCase() as DictionaryKey) || tg}</span>
                          })}
                        </div>
                      )}
                      <div className="flex items-center gap-3 mt-1.5">
                        <div className="flex-1 h-1.5 bg-slate-200 dark:bg-secondary/60 rounded-full overflow-hidden max-w-[120px]">
                          <div className={cn('h-full rounded-full', bullish ? 'bg-[#059669] dark:bg-[#0ecb81]' : 'bg-[#e11d48] dark:bg-[#f6465d]')} style={{ width: `${it * 100}%` }} />
                        </div>
                        <span className={cn('text-[10px] font-mono font-bold', bullish ? 'text-[#059669] dark:text-[#0ecb81]' : 'text-[#e11d48] dark:text-[#f6465d]')}>{score > 0 ? '+' : ''}{score}</span>
                      </div>
                    </div>
                    <div className="flex-shrink-0 flex flex-col items-end gap-1.5"><span className={cn('text-[10px] font-bold px-2 py-0.5 rounded uppercase', bullish ? 'bg-[#0ecb81]/15 text-[#059669] dark:text-[#0ecb81]' : 'bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]')}>{label}</span><span className="text-[10px] text-muted-foreground font-mono">{ts}</span></div>
                  </div>
                  {(summaryZh || reasoning) && (
                    <div className="pl-5 border-t border-border/10 mt-1.5 pt-2 space-y-1.5">{summaryZh && <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2"><HighlightedText text={summaryZh} /></p>}{reasoning && <div className="flex items-start gap-1.5"><span className="text-[9px] text-indigo-400 font-mono shrink-0 mt-0.5 uppercase tracking-wider">AI Insight:</span><p className="text-[10px] text-muted-foreground/60 italic line-clamp-2"><HighlightedText text={reasoning} /></p></div>}</div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
        {visibleNewsCount < news.length && (
          <button onClick={() => setVisibleNewsCount(v => v + 5)} className="w-full py-2.5 text-[10px] text-muted-foreground hover:bg-secondary/40 hover:text-foreground transition-colors outline-none font-medium">⬇ 点击加载更多快讯 ({visibleNewsCount} / {news.length})</button>
        )}
      </div>
    </div>
  );
}