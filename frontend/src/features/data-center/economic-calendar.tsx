import React from 'react';
import { AlertTriangle, Info, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import EventCountdown from '@/components/ui/event-countdown';
import { CalendarInfoPanel, EventDetailPanel } from './event-panels';

export function EconomicCalendar({
  events,
  calendarInfo,
  setCalendarInfo,
  selectedEvent,
  setSelectedEvent,
  selectedDateFilter,
  setSelectedDateFilter,
  selectedCountry,
  setSelectedCountry,
  selectedImpacts,
  setSelectedImpacts,
  uniqueCountries,
  ecoMsg,
  ecoDed,
  handleManualRefresh
}: any) {
  const today = new Date();
  const todayStr = today.toISOString().split('T')[0];
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const tomorrowStr = tomorrow.toISOString().split('T')[0];

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      {calendarInfo && <CalendarInfoPanel onClose={() => setCalendarInfo(false)} />}
      {selectedEvent && <EventDetailPanel event={selectedEvent} onClose={() => setSelectedEvent(null)} />}
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 flex-shrink-0">
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 dark:text-amber-400" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">经济日历 · 央行事件</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setCalendarInfo(true)} className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground bg-secondary/30 hover:bg-secondary/60 px-2 py-0.5 rounded-full transition-colors">
            <Info className="h-3 w-3" /><span>说明</span>
          </button>
          <div className="flex items-center bg-secondary/30 rounded-full p-0.5 border border-border/20">
            {[
              { id: 'past', label: '过去' },
              { id: 'all', label: '全部' },
              { id: 'today', label: '今日' },
              { id: 'tomorrow', label: '明日' },
            ].map(df => {
              const active = selectedDateFilter === df.id;
              return (
                <button
                  key={df.id}
                  onClick={() => setSelectedDateFilter(df.id as any)}
                  className={cn("flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full transition-colors", active ? `bg-primary/10 text-primary font-bold` : "text-muted-foreground hover:text-foreground")}
                  title={df.id === 'past' ? '显示过去已公布的数据' : `仅显示${df.label}事件`}
                >
                  {df.label}
                </button>
              )
            })}
          </div>
          <select
            value={selectedCountry}
            onChange={(e) => setSelectedCountry(e.target.value)}
            className="bg-secondary/30 border border-transparent hover:bg-secondary/60 text-muted-foreground text-[10px] rounded-full px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
            aria-label="筛选国家"
          >
            {uniqueCountries.map((c: string) => <option key={c} value={c}>{c === 'all' ? '全部国家' : c}</option>)}
          </select>
          <div className="flex items-center bg-secondary/30 rounded-full p-0.5 border border-border/20">
            {[
              { id: 'high', label: '高', color: 'text-[#e11d48] dark:text-[#f6465d]', bg: 'bg-[#f6465d]/15' },
              { id: 'medium', label: '中', color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-500/15' },
              { id: 'low', label: '低', color: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-500/15' }
            ].map(imp => {
              const active = selectedImpacts.includes(imp.id);
              return (
                <button
                  key={imp.id}
                  onClick={() => setSelectedImpacts((prev: string[]) => prev.includes(imp.id) ? prev.filter(x => x !== imp.id) : [...prev, imp.id])}
                  className={cn(
                    "flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full transition-colors",
                    active ? `${imp.bg} ${imp.color} font-bold` : "text-muted-foreground hover:text-foreground"
                  )}
                  title={`显示/隐藏 ${imp.label} 级别事件`}
                >
                  {imp.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {ecoMsg && (
          <div className="m-2 p-2 flex items-center gap-2 rounded-md bg-amber-500/10 text-[10px] text-amber-600 dark:text-amber-500 border border-amber-500/20">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            <p>{ecoMsg}</p>
          </div>
        )}
        {ecoDed && (
          <div className="m-2 p-3 rounded-lg bg-indigo-500/10 border border-indigo-500/20 shadow-inner">
            <div className="flex items-center gap-2 mb-1.5 text-indigo-600 dark:text-indigo-400 font-bold text-[11px]">
              <Sparkles className="h-3.5 w-3.5" />
              <span>🧠 主脑前瞻推演 (AI Foresight)</span>
            </div>
            <p className="text-[10px] text-slate-600 dark:text-slate-300 leading-relaxed">
              {ecoDed}
            </p>
          </div>
        )}
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/30 bg-slate-50 dark:bg-secondary/20 sticky top-0 z-10 backdrop-blur-md"><th className="text-left px-3 py-1.5 text-muted-foreground font-medium">日期</th><th className="text-left px-2 py-1.5 text-muted-foreground font-medium">时间</th><th className="text-left px-2 py-1.5 text-muted-foreground font-medium">地区</th><th className="text-left px-2 py-1.5 text-muted-foreground font-medium">事件</th><th className="text-center px-2 py-1.5 text-muted-foreground font-medium">级别</th><th className="text-right px-2 py-1.5 text-muted-foreground font-medium">实际</th><th className="text-right px-2 py-1.5 text-muted-foreground font-medium">预期</th><th className="text-right px-3 py-1.5 text-muted-foreground font-medium">前值</th></tr>
          </thead>
          <tbody className="divide-y divide-border/15">
            {events
              .filter((ev: any) => {
                if (selectedDateFilter === 'all') return true;
                const eventDate = ev.date?.split('T')[0];
                if (selectedDateFilter === 'today') return eventDate === todayStr;
                if (selectedDateFilter === 'tomorrow') return eventDate === tomorrowStr;
                // 💡 过去：显示今天之前的事件
                if (selectedDateFilter === 'past') return eventDate && eventDate < todayStr;
                return false;
              })
              .filter((ev: any) => selectedImpacts.includes(ev.impact?.toLowerCase() || 'medium'))
              .filter((ev: any) => selectedCountry === 'all' || ev.country === selectedCountry)
              .map((ev: any, i: number) => { 
              let dd = ev.date, dt = ev.time; 
              if (ev.date?.includes('T')) { const p = ev.date.split('T'); dd = p[0]; dt = p[1].replace('Z', '').substring(0, 5) } 
              const imp = ev.impact?.toLowerCase() || 'medium'; 
              const isHigh = imp === 'high';
              const isLow = imp === 'low';
              
              // 动态计算实际值的偏离颜色
              let actualColor = ev.actual ? "text-foreground" : "text-muted-foreground";
              let deviationArrow = "";
              if (ev.actual && (ev.forecast || ev.estimate)) {
                const aNum = parseFloat(String(ev.actual).replace(/[^0-9.-]/g, ''));
                const fNum = parseFloat(String(ev.forecast || ev.estimate).replace(/[^0-9.-]/g, ''));
                if (!isNaN(aNum) && !isNaN(fNum) && aNum !== fNum) {
                  const evName = String(ev.event_zh || ev.event_cn || ev.title_zh || ev.event || '').toLowerCase();
                  const invert = /失业|unemployment|jobless|claims/.test(evName); // 智能反转失业率等逆向指标
                  const isBetter = aNum > fNum;
                  deviationArrow = aNum > fNum ? "↑" : "↓";
                  actualColor = (isBetter && !invert) || (!isBetter && invert) ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]";
                }
              }

              return (
                <tr key={i} onClick={() => setSelectedEvent(ev)} className={cn('transition-all cursor-pointer', isHigh ? 'bg-[#f6465d]/5 hover:bg-[#f6465d]/10 border-l-2 border-l-[#f6465d]' : 'opacity-80 hover:opacity-100 hover:bg-slate-50 dark:hover:bg-secondary/30')}>
                  <td className="px-3 py-2 font-mono text-[9px] text-muted-foreground whitespace-nowrap">{dd}</td>
                  <td className="px-2 py-2 whitespace-nowrap">
                    <div className="font-mono text-[9px] text-muted-foreground mb-1.5">{dt}</div>
                    <EventCountdown dateIso={ev.date} actual={ev.actual} onRefresh={handleManualRefresh} />
                  </td>
                  <td className="px-2 py-2"><span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded", isHigh ? "bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]" : "bg-secondary/60 text-muted-foreground")}>{ev.country}</span></td>
                  <td className={cn("px-2 py-2 leading-tight", isHigh ? "font-bold text-foreground" : "font-medium text-muted-foreground text-[10px]")}>{ev.event_zh || ev.event_cn || ev.title_zh || ev.event}</td>
                  <td className="px-2 py-2 text-center"><span className={cn('inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold tracking-widest', isHigh ? 'text-[#e11d48] dark:text-[#f6465d]' : isLow ? 'text-sky-600/70 dark:text-sky-400/70' : 'text-amber-500/70 dark:text-amber-400/70')}>{isHigh ? '●●●' : isLow ? '●' : '●●'}</span></td>
                  <td className={cn("px-2 py-2 text-right font-mono text-[10px] whitespace-nowrap", ev.actual && "font-bold", actualColor)}>
                    {ev.actual || '-'}
                    {deviationArrow && <span className="ml-0.5 inline-block">{deviationArrow}</span>}
                  </td>
                  <td className={cn("px-2 py-2 text-right font-mono text-[10px]", isHigh ? "text-foreground" : "text-muted-foreground")}>{ev.forecast || ev.estimate || '-'}</td>
                  <td className="px-3 py-2 text-right font-mono text-[10px] text-muted-foreground/60">{ev.prev || ev.previous || '-'}</td>
                </tr>
              ) 
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}