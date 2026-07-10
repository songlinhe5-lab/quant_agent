import React from 'react';
import { LineChartIcon, Sparkles } from 'lucide-react';
import EventCountdown from '@/components/ui/event-countdown';

export function EarningsCalendar({ earnings, earnDed, handleManualRefresh }: { earnings: any[], earnDed: string, handleManualRefresh: () => void }) {
  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col h-[350px] relative">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2 flex-shrink-0">
        <LineChartIcon className="h-3.5 w-3.5 text-emerald-500 dark:text-emerald-400" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">本周核心财报前瞻</span>
        <span className="ml-auto text-[10px] text-muted-foreground font-mono">
          共 {earnings.length} 家明星公司
        </span>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar relative">
        {earnDed && (
          <div className="m-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 shadow-inner">
            <div className="flex items-center gap-2 mb-1.5 text-emerald-600 dark:text-emerald-400 font-bold text-[11px]">
              <Sparkles className="h-3.5 w-3.5" />
              <span>🧠 财报季风暴预演 (Earnings Foresight)</span>
            </div>
            <p className="text-[10px] text-slate-600 dark:text-slate-300 leading-relaxed tracking-wide">
              {earnDed}
            </p>
          </div>
        )}
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-slate-50 dark:bg-secondary/20 backdrop-blur-md border-b border-border/30">
            <tr>
              <th className="text-left px-3 py-1.5 text-muted-foreground font-medium">日期 (UTC)</th>
              <th className="text-left px-2 py-1.5 text-muted-foreground font-medium">标的</th>
              <th className="text-left px-2 py-1.5 text-muted-foreground font-medium">中文名称</th>
              <th className="text-center px-2 py-1.5 text-muted-foreground font-medium">财报季度</th>
              <th className="text-right px-3 py-1.5 text-muted-foreground font-medium">华尔街预期 EPS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/15">
            {earnings.map((ea: any, i: number) => {
              const isoTime = `${ea.date}T20:30:00Z`;
              return (
                <tr key={i} className="hover:bg-slate-50 dark:hover:bg-secondary/30 transition-colors">
                  <td className="px-3 py-2 whitespace-nowrap"><div className="font-mono text-[10px] text-muted-foreground mb-1.5">{ea.date}</div><EventCountdown dateIso={isoTime} actual={ea.epsActual} onRefresh={handleManualRefresh} /></td>
                  <td className="px-2 py-2 font-bold font-mono text-[11px] text-foreground">{ea.symbol}</td>
                  <td className="px-2 py-2 text-[10px] text-muted-foreground">{ea.name_cn || '-'}</td>
                  <td className="px-2 py-2 text-center font-mono text-[10px] text-muted-foreground">Q{ea.quarter}</td><td className="px-3 py-2 text-right font-mono text-[10px] text-emerald-600 dark:text-emerald-400 font-bold">{ea.epsEstimate ? `$${ea.epsEstimate}` : '-'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {earnings.length === 0 && <div className="p-4 text-center text-[10px] text-muted-foreground">本周暂无明星公司财报</div>}
      </div>
    </div>
  );
}