import React from 'react';
import { Newspaper } from 'lucide-react';
import { cn } from '@/lib/utils';
import { HighlightedText, NEWS_TAG_COLORS } from './shared';
import { useI18n, type DictionaryKey } from '@/contexts/i18n';
import { useTheme } from 'next-themes';

export function NewsStream({ news, visibleNewsCount, setVisibleNewsCount, className }: { news: any[], visibleNewsCount: number, setVisibleNewsCount: React.Dispatch<React.SetStateAction<number>>, className?: string }) {
  const { t } = useI18n();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // 💡 真实展示新闻发布相对时间, 并对显著滞后(>6h)的新闻标注"源延迟",
  // 避免用户误以为系统卡顿; 不伪造时间戳, 符合零幻觉红线。
  const formatNewsTime = (n: any): { text: string; delayed: boolean } => {
    let tsSec: number | null = null;
    if (n.datetime != null) {
      const v = Number(n.datetime);
      tsSec = v > 1e11 ? v / 1000 : v; // 兼容秒/毫秒级时间戳
    } else if (n.time && !isNaN(Date.parse(n.time))) {
      tsSec = Date.parse(n.time) / 1000;
    }
    if (tsSec == null || isNaN(tsSec)) return { text: '最近', delayed: false };
    const diffSec = Math.floor(Date.now() / 1000 - tsSec);
    if (diffSec < 0) return { text: '刚刚', delayed: false };
    if (diffSec < 60) return { text: '刚刚', delayed: false };
    if (diffSec < 3600) return { text: `${Math.floor(diffSec / 60)} 分钟前`, delayed: false };
    if (diffSec < 86400) return { text: `${Math.floor(diffSec / 3600)} 小时前`, delayed: diffSec > 6 * 3600 };
    return { text: `${Math.floor(diffSec / 86400)} 天前`, delayed: true };
  };

  return (
    <div className={cn('glass-card rounded-lg overflow-hidden flex flex-col', className || 'h-[350px]')}>
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 flex-shrink-0">
        <Newspaper className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">LLM 情感打分 · 财经快讯</span>
        <span className="ml-auto text-[10px] text-muted-foreground font-mono flex items-center gap-1.5">
          {news.length > 0 ? `共 ${news.length} 条` : ''}
          <span className="text-[9px] text-amber-500/80 border border-amber-500/20 px-1 py-0.5 rounded" title="Finnhub 免费档行情新闻端点为延迟缓存，非实时推送">源延迟</span>
        </span>
      </div>
      <div className="flex-1 divide-y divide-border/15 overflow-y-auto custom-scrollbar">
        {news.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center gap-2 py-10 text-center px-4">
            <Newspaper className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">暂无财经快讯</p>
            <p className="text-[10px] text-muted-foreground/60">新闻采集暂时不可用，恢复后将自动刷新</p>
          </div>
        )}
        {news.slice(0, visibleNewsCount).map((n: any, i: number) => {
          const titleText = n.title || n.headline || '未知';
          const timeInfo = formatNewsTime(n);

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
                          <div className={cn('h-full rounded-full', bullish ? 'bg-[#10B981] dark:bg-[#34D399]' : 'bg-[#EF4444] dark:bg-[#F87171]')} style={{ width: `${it * 100}%` }} />
                        </div>
                        <span className={cn('text-[10px] font-mono font-bold', bullish ? 'text-[#10B981] dark:text-[#34D399]' : 'text-[#EF4444] dark:text-[#F87171]')}>{score > 0 ? '+' : ''}{score}</span>
                      </div>
                    </div>
                    <div className="flex-shrink-0 flex flex-col items-end gap-1.5"><span className={cn('text-[10px] font-bold px-2 py-0.5 rounded uppercase', bullish ? 'bg-[#34D399]/15 text-[#10B981] dark:text-[#34D399]' : 'bg-[#F87171]/15 text-[#EF4444] dark:text-[#F87171]')}>{label}</span><span className="text-[10px] text-muted-foreground font-mono">{timeInfo.text}</span>{timeInfo.delayed && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-500 border border-amber-500/30 whitespace-nowrap">源延迟</span>}</div>
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
