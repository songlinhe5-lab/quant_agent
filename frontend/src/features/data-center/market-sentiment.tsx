import React, { useState, useEffect } from 'react'
import { Gauge, Info, X, Activity } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MiniTrendLine } from './shared'

export function SentimentInfoPanel({ onClose }: { onClose: () => void }) {
  const indicators = [
    { name: '贪婪恐惧指数 (F&G Index)', desc: '综合了市场动量、股票强度、波动率等多个维度，衡量散户的整体情绪。数值越高越贪婪，越低越恐慌，是经典的逆向指标。' },
    { name: '恐慌指数 (VIX)', desc: '衡量标普500指数未来30天的预期波动率。VIX 飙升通常意味着市场恐慌加剧，避险情绪浓厚。' },
    { name: '期权 P/C Ratio', desc: '看跌期权(Put)与看涨期权(Call)的成交量比率。比率大于1意味着市场看空情绪占优，小于1则看多情绪占优，同样是重要的逆向参考。' },
    { name: '高收益债利差 (HY Spread)', desc: '高收益企业债（垃圾债）与无风险国债的收益率之差。利差扩大意味着信贷市场认为违约风险上升，是系统性流动性危机的重要预警信号。' },
  ]
  return (
    <div className="absolute inset-0 z-20 bg-black/60 backdrop-blur-sm rounded-lg flex items-center justify-center p-3 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full h-full bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
          <h3 className="text-xs font-bold flex items-center gap-1.5"><Gauge className="h-3 w-3 text-muted-foreground" />市场情绪风向标 · 指标说明</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary/50" aria-label="关闭"><X className="h-3.5 w-3.5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {indicators.map(ind => (
            <div key={ind.name} className="p-3 border border-border/30 rounded-lg bg-secondary/20">
              <h4 className="text-xs font-bold text-foreground mb-1">{ind.name}</h4>
              <p className="text-[11px] text-muted-foreground leading-relaxed">{ind.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function MarketSentimentPanel({ vixData, sentimentInd }: { vixData: any, sentimentInd?: any }) {
  const [showInfo, setShowInfo] = useState(false)
  const [fgScore, setFgScore] = useState(74);
  
  const [mockSparklines] = useState(() => {
    const genTrend = (start: number, vol: number) => {
      let curr = start;
      return Array.from({length: 30}, () => { curr += (Math.random() - 0.5) * vol; return curr; });
    };
    return { fg: genTrend(60, 5), vix: genTrend(18, 2), pc: genTrend(0.9, 0.05), cs: genTrend(3.8, 0.1) }
  });

  useEffect(() => {
    const timer = setInterval(() => {
       if (document.hidden) return;
       setFgScore(prev => Math.max(0, Math.min(100, prev + Math.floor(Math.random() * 5) - 2)));
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  let fgLabel = '中性';
  let fgColor = 'text-amber-500';
  if (fgScore >= 75) { fgLabel = '极度贪婪'; fgColor = 'text-[#059669] dark:text-[#0ecb81]'; }
  else if (fgScore >= 55) { fgLabel = '贪婪'; fgColor = 'text-[#059669] dark:text-[#0ecb81]'; }
  else if (fgScore <= 25) { fgLabel = '极度恐惧'; fgColor = 'text-[#e11d48] dark:text-[#f6465d]'; }
  else if (fgScore <= 45) { fgLabel = '恐惧'; fgColor = 'text-[#e11d48] dark:text-[#f6465d]'; }

  const pcVal = sentimentInd?.pc_ratio?.value ?? 0.82;
  const pcStatus = sentimentInd?.pc_ratio?.status ?? '偏多';
  const csVal = sentimentInd?.credit_spread?.value ?? 3.45;
  const csStatus = sentimentInd?.credit_spread?.status ?? '安全';

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col relative h-full">
      {showInfo && <SentimentInfoPanel onClose={() => setShowInfo(false)} />}
      <div className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2">
        <Gauge className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">市场情绪风向标</span>
        <button onClick={() => setShowInfo(true)} className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground bg-secondary/30 hover:bg-secondary/60 px-2 py-0.5 rounded-full">
          <Info className="h-3 w-3" /><span>指标说明</span>
        </button>
      </div>
      <div className="p-4 flex-1 flex flex-col justify-center gap-5">
        <div className="flex flex-col gap-2.5">
          <div className="flex items-end justify-between">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground font-semibold">贪婪恐惧指数</span>
              <div className="opacity-60"><MiniTrendLine data={mockSparklines.fg} isPositive={fgScore >= 50} /></div>
            </div>
            <div className="flex items-baseline gap-1.5"><span className={cn("text-2xl font-bold font-mono tabular-nums leading-none transition-colors duration-500", fgColor)}>{fgScore}</span><span className={cn("text-[10px] font-bold uppercase transition-colors duration-500", fgColor)}>{fgLabel}</span></div>
          </div>
          <div className="relative h-2 w-full rounded-full bg-gradient-to-r from-[#e11d48] via-amber-500 to-[#059669] dark:from-[#f6465d] dark:to-[#0ecb81] opacity-90 overflow-hidden">
             <div className="absolute top-0 bottom-0 w-1 bg-white shadow-[0_0_5px_rgba(255,255,255,1)] rounded-full transition-all duration-1000 ease-out" style={{ left: `${fgScore}%`, transform: 'translateX(-50%)' }} />
          </div>
        </div>
        <div className="flex flex-col gap-1.5 pt-3 border-t border-border/20">
          <div className="flex items-center justify-between"><span className="text-[10px] text-muted-foreground font-semibold flex items-center gap-1"><Activity className="h-3 w-3" /> 恐慌指数 (VIX)</span>{vixData ? (<div className="flex items-center gap-2"><div className="opacity-60"><MiniTrendLine data={vixData.sparkline || mockSparklines.vix} isPositive={vixData.change <= 0} /></div><div className="flex items-baseline gap-1.5"><span className="text-sm font-bold font-mono tabular-nums">{vixData.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span><span className={cn("text-[10px] font-mono font-bold", vixData.change >= 0 ? "text-[#e11d48] dark:text-[#f6465d]" : "text-[#059669] dark:text-[#0ecb81]")}>{vixData.change >= 0 ? '+' : ''}{vixData.change.toFixed(2)}%</span></div></div>) : (<span className="text-xs text-muted-foreground">--</span>)}</div>
          <div className="text-[9px] text-muted-foreground leading-relaxed mt-1">{vixData?.value < 15 ? '隐含波动率处于低位，市场风险偏好较高，单边或缓涨行情为主。' : vixData?.value > 25 ? '隐含波动率大幅飙升，避险情绪浓厚，警惕资产价格尾部风险。' : '波动率处于历史均值区间，多空博弈分歧加剧，市场呈震荡态势。'}</div>
          <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-border/10">
            <div className="flex flex-col gap-1"><div className="flex items-center justify-between"><span className="text-[9px] text-muted-foreground">期权 P/C Ratio</span><div className="opacity-60 scale-75 origin-right"><MiniTrendLine data={sentimentInd?.pc_ratio?.sparkline || mockSparklines.pc} isPositive={pcVal < 1.0} /></div></div><span className="text-xs font-mono font-bold text-foreground -mt-1">{pcVal.toFixed(2)} <span className={cn("text-[8px] ml-1", pcVal < 1.0 ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]")}>{pcStatus}</span></span></div>
            <div className="flex flex-col gap-1"><div className="flex items-center justify-between"><span className="text-[9px] text-muted-foreground">高收益债利差</span><div className="opacity-60 scale-75 origin-right"><MiniTrendLine data={sentimentInd?.credit_spread?.sparkline || mockSparklines.cs} isPositive={csVal < 4.5} /></div></div><span className="text-xs font-mono font-bold text-foreground -mt-1">{csVal.toFixed(2)}% <span className={cn("text-[8px] ml-1", csVal < 4.5 ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]")}>{csStatus}</span></span></div>
          </div>
        </div>
      </div>
    </div>
  )
}