import React from 'react'
import { X, AlertTriangle, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTheme } from 'next-themes'

export const RADAR_AXIS_INFO = [
  { key: '流动性', desc: '衡量全球离岸美元流动性充裕度', calc: 'USD/JPY 涨跌幅 × VIX 涨跌幅 等权反向 Sigmoid 合成', range: '0 (枯竭) → 100 (极度充裕)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：Carry Trade 活跃</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：中性震荡</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：流动性骤紧</li></ul>) },
  { key: '波动率', desc: '市场恐慌水位', calc: '100 − (VIX − 10) × 2.5，截断 [0,100]', range: '0 (恐慌) → 100 (舒适)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：VIX {'<'}15</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：VIX 15–25</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：VIX {'>'}30</li></ul>) },
  { key: '权益', desc: '全球股指动量共振', calc: 'SPX+IXIC+HSI+HSTECH+N225 等权正向 Sigmoid', range: '0 (崩塌) → 100 (普涨)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：普涨乐观</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：分化</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：避险</li></ul>) },
  { key: '商品', desc: '大宗商品需求与通胀', calc: 'XAU+WTI 等权正向 Sigmoid', range: '0 (通缩) → 100 (过热)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：通胀预期升温</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：平衡</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：通缩恐慌</li></ul>) },
  { key: '债券', desc: '债券风险偏好信号', calc: '10Y 收益率涨跌幅反向 Sigmoid', range: '0 (避险) → 100 (风险偏好)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：债牛=宽松预期</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：横盘</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：债崩=风险承压</li></ul>) },
  { key: '汇率', desc: '美元强弱传导', calc: 'DXY 涨跌幅反向 Sigmoid', range: '0 (强美元) → 100 (弱美元)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：弱美元宽松</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：均衡</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：强势承压</li></ul>) },
  { key: '中概强度', desc: '中国海外核心资产动量', calc: 'HSI+KWEB 等权正向 Sigmoid', range: '0 (恐慌抛售) → 100 (外资抢筹)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：强力买入</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：横盘分歧</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：承压离场</li></ul>) },
  { key: '数字货币', desc: '加密资产投机情绪', calc: 'BTC+ETH 等权正向 Sigmoid (平滑缩放因子)', range: '0 (流动性抽离) → 100 (FOMO 狂暴)', phenomenon: (<ul className="space-y-1 mt-1"><li><span className="text-emerald-400 font-bold">高分 {'>'}70</span>：风险极度偏好</li><li><span className="text-amber-400 font-bold">中分 40–60</span>：区间震荡</li><li><span className="text-red-400 font-bold">低分 {'<'}30</span>：恐慌抛售</li></ul>) },
]

export function RadarInfoPanel({ radarData, onClose }: { radarData: any[]; onClose: () => void }) {
  return (<div className="absolute inset-0 z-20 bg-black/60 backdrop-blur-sm rounded-lg flex items-center justify-center p-3"><div className="w-full h-full bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col"><div className="flex items-center justify-between px-3 py-2 border-b border-border/30"><h3 className="text-xs font-bold">宏观风险雷达 · 算法面板</h3><button onClick={onClose} className="p-1 rounded hover:bg-secondary/50" aria-label="关闭"><X className="h-3.5 w-3.5" /></button></div><div className="flex-1 overflow-y-auto space-y-2 p-3">{RADAR_AXIS_INFO.map(a => { const s = radarData.find((r:any) => r.axis === a.key)?.current ?? 50; return (<details key={a.key} className="group border border-border/20 rounded-lg overflow-hidden"><summary className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-secondary/20 text-xs font-semibold"><span className={cn('h-2 w-2 rounded-full', s >= 70 ? 'bg-emerald-400' : s >= 40 ? 'bg-amber-400' : 'bg-red-400')} />{a.key}<span className="ml-auto font-mono text-[10px] text-muted-foreground">当前: {s}</span></summary><div className="px-3 pb-3 space-y-1.5 text-[10px] text-muted-foreground border-t border-border/10 pt-2"><p><span className="text-foreground font-medium">定义：</span>{a.desc}</p><p><span className="text-foreground font-medium">算法：</span><code className="text-[9px] bg-secondary/50 px-1 py-0.5 rounded">{a.calc}</code></p><p><span className="text-foreground font-medium">量程：</span>{a.range}</p><div><span className="text-foreground font-medium">现象解读：</span>{a.phenomenon}</div></div></details>) })}</div><div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center">数据来源: yfinance · 归一化: Sigmoid</div></div></div>)
}

export function CalendarInfoPanel({ onClose }: { onClose: () => void }) {
  const indicators = [
    { name: '美联储 (FED) 利率决议', desc: '全球流动性的总闸门。加息或降息预期直接影响美元指数与全球大类资产定价及资金流向。' },
    { name: '非农就业与通胀 (CPI/PCE)', desc: '反映美国经济冷热与通胀压力的核心数据，是央行货币政策转向的重要前瞻指引。' },
    { name: '欧洲/日本央行 (ECB/BOJ)', desc: '直接影响欧元/日元汇率，进而引发全球套息交易 (Carry Trade) 资金的大规模平仓或建仓。' },
    { name: '事件影响力评级', desc: '红点 (●●●) 代表高影响核心事件，极易引发标普、纳指与汇率市场的剧烈震荡；黄点 (●●) 代表中等影响数据；蓝点 (●) 代表低影响数据。' },
  ]
  return (
    <div className="absolute inset-0 z-20 bg-black/60 backdrop-blur-sm rounded-lg flex items-center justify-center p-3 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full h-full bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
          <h3 className="text-xs font-bold flex items-center gap-1.5"><AlertTriangle className="h-3 w-3 text-amber-500" />经济日历 · 指标说明</h3>
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

export function EventDetailPanel({ event, onClose }: { event: any; onClose: () => void }) {
  const { theme } = useTheme()
  const evName = event.event_zh || event.event_cn || event.title_zh || event.event;
  
  let actualColor = event.actual ? "text-foreground" : "text-muted-foreground";
  let deviationArrow = "";
  if (event.actual && (event.forecast || event.estimate)) {
    const aNum = parseFloat(String(event.actual).replace(/[^0-9.-]/g, ''));
    const fNum = parseFloat(String(event.forecast || event.estimate).replace(/[^0-9.-]/g, ''));
    if (!isNaN(aNum) && !isNaN(fNum) && aNum !== fNum) {
      const invert = /失业|unemployment|jobless|claims/.test(String(evName).toLowerCase());
      const isBetter = aNum > fNum;
      deviationArrow = aNum > fNum ? "↑" : "↓";
      actualColor = (isBetter && !invert) || (!isBetter && invert) ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]";
    }
  }
  
  const imp = event.impact?.toLowerCase() || 'medium';
  const isHigh = imp === 'high';
  const isLow = imp === 'low';

  let dt = event.time;
  if (!dt && event.date?.includes('T')) {
    dt = event.date.split('T')[1].replace('Z', '').substring(0, 5);
  }
  const dd = event.date?.includes('T') ? event.date.split('T')[0] : event.date;

  return (
    <div className="absolute inset-0 z-20 bg-black/60 backdrop-blur-sm rounded-lg flex items-center justify-center p-3 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full h-full bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/30 bg-secondary/20">
          <h3 className="text-xs font-bold flex items-center gap-1.5 truncate pr-2">
            <AlertTriangle className={cn("h-3 w-3 shrink-0", isHigh ? "text-[#e11d48] dark:text-[#f6465d]" : isLow ? "text-sky-500 dark:text-sky-400" : "text-amber-500")} />
            <span className="truncate">{evName}</span>
          </h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary/50 text-muted-foreground hover:text-foreground shrink-0" aria-label="关闭"><X className="h-3.5 w-3.5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar">
          <div className="flex items-center gap-2">
            <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded", isHigh ? "bg-[#f6465d]/15 text-[#e11d48] dark:text-[#f6465d]" : "bg-secondary text-muted-foreground")}>{event.country}</span>
            <span className="text-[10px] text-muted-foreground font-mono bg-secondary/40 px-2 py-0.5 rounded">{dd} {dt}</span>
            <span className={cn('inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold tracking-widest', isHigh ? 'text-[#e11d48] dark:text-[#f6465d]' : isLow ? 'text-sky-600/70 dark:text-sky-400/70' : 'text-amber-500/70 dark:text-amber-400/70')}>{isHigh ? '●●●' : isLow ? '●' : '●●'}</span>
          </div>
          
          <div className="grid grid-cols-3 gap-2 p-2.5 bg-secondary/20 rounded-lg border border-border/30">
            <div className="flex flex-col gap-1">
              <span className="text-[9px] text-muted-foreground">前值 (Prev)</span>
              <span className="font-mono text-xs text-muted-foreground">{event.prev || event.previous || '-'}</span>
            </div>
            <div className="flex flex-col gap-1 border-l border-border/30 pl-2">
              <span className="text-[9px] text-muted-foreground">预期 (Fcst)</span>
              <span className="font-mono text-xs text-foreground">{event.forecast || event.estimate || '-'}</span>
            </div>
            <div className="flex flex-col gap-1 border-l border-border/30 pl-2">
              <span className="text-[9px] text-muted-foreground font-semibold">实际 (Act)</span>
              <span className={cn("font-mono text-xs font-bold whitespace-nowrap", actualColor)}>
                {event.actual || '-'}
                {deviationArrow && <span className="ml-1 inline-block text-[10px]">{deviationArrow}</span>}
              </span>
            </div>
          </div>
          
          <div className="space-y-1.5">
            <h4 className="text-[10px] font-bold text-muted-foreground uppercase flex items-center gap-1">
              <Sparkles className="h-3 w-3 text-indigo-500 dark:text-indigo-400" /> AI 智能推演
            </h4>
            <div className="p-2.5 bg-indigo-500/5 dark:bg-indigo-400/10 border border-indigo-500/20 dark:border-indigo-400/20 rounded-lg text-[10px] text-muted-foreground leading-relaxed">
              {event.actual ? (
                <>
                  实际数据录得 <strong className={actualColor}>{event.actual}</strong>，对比预期 {event.forecast || '-'}。<br/>
                  {deviationArrow === '↑' ? "数据表现强于预期，" : deviationArrow === '↓' ? "数据表现不及预期，" : "数据符合预期，"}
                  此偏差通常会对 {event.country} 相关汇率及权益资产产生边际影响。请结合当前大类资产估值水位与情绪指标 (VIX/HY Spread) 综合评估尾部风险。
                </>
              ) : (
                <>
                  该事件数据尚未公布 (等待落地)。<br/>
                  高关注度宏观数据公布瞬间极易引发资产的流动性真空与双向宽幅震荡。建议在落地前做好敞口对冲与多空杠杆平衡。
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}