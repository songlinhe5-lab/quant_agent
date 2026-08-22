import React, { useState } from 'react'
import type { EChartsCoreOption } from 'echarts'
import { Gauge, Info, X, Activity } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Sparkline } from '@/components/ui/data-display/sparkline'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

export function SentimentInfoPanel({ onClose }: { onClose: () => void }) {
  const indicators = [
    { name: '贪婪恐惧指数 (F&G Index)', desc: '综合了市场动量、股票强度、波动率等多个维度，衡量散户的整体情绪。数值越高越贪婪，越低越恐慌，是经典的逆向指标。' },
    { name: '恐慌指数 (VIX)', desc: '衡量标普500指数未来30天的预期波动率。VIX 飙升通常意味着市场恐慌加剧，避险情绪浓厚。' },
    { name: '期权 P/C Ratio', desc: '看跌期权(Put)与看涨期权(Call)的成交量比率。比率大于1意味着市场看空情绪占优，小于1则看多情绪占优，同样是重要的逆向参考。' },
    { name: '高收益债利差 (HY Spread)', desc: '高收益企业债（垃圾债）与无风险国债的收益率之差。利差扩大意味着信贷市场认为违约风险上升，是系统性流动性危机的重要预警信号。' },
    { name: '散户热度 (ApeWisdom)', desc: 'ApeWisdom 社区 top-N 标的的提及量（mentions）环比变化。⚠️ 热度 ≠ 情绪：这是「散户注意力突变」指标，反映关注度激增/骤冷，不代表看多或看空方向，需与 P/C、VIX 等方向性指标分开解读。' },
  ]
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-3xl h-full max-h-[85vh] bg-card border border-border/40 rounded-lg overflow-hidden flex flex-col shadow-xl" onClick={e => e.stopPropagation()}>
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

// SENT-01：情绪因子历史折线（VIX 左轴 / P/C 右轴），真实数据来自 /macro/sentiment-history
function SentimentHistoryChart({ history }: { history: any[] }) {
  const ref = useEChart((): EChartsCoreOption | null => {
    if (!history || history.length === 0) return null
    const dates = history.map(r => (r.time || '').slice(0, 11))
    const vix = history.map(r => (r.vix != null ? Number(r.vix.toFixed(2)) : null))
    const pc = history.map(r => (r.pc_ratio != null ? Number(r.pc_ratio.toFixed(3)) : null))
    const heat = history.map(r => (r.retail_heat_change_pct != null ? Number((r.retail_heat_change_pct * 100).toFixed(1)) : null))
    return {
      grid: { left: 38, right: 40, top: 24, bottom: 24 },
      tooltip: { trigger: 'axis', backgroundColor: ECHART_DARK.tooltipBg, borderColor: ECHART_DARK.split, textStyle: { color: ECHART_DARK.text, fontSize: 10 } },
      legend: { data: ['VIX', 'P/C', '散户热度'], textStyle: { color: ECHART_DARK.text, fontSize: 10 }, top: 0, right: 0 },
      xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: ECHART_DARK.split } }, axisLabel: { color: ECHART_DARK.text, fontSize: 9, hideOverlap: true } },
      yAxis: [
        { type: 'value', name: 'VIX', scale: true, nameTextStyle: { color: ECHART_DARK.text, fontSize: 9 }, axisLabel: { color: ECHART_DARK.text, fontSize: 9 }, splitLine: { lineStyle: { color: ECHART_DARK.split } } },
        { type: 'value', name: 'P/C', scale: true, nameTextStyle: { color: ECHART_DARK.text, fontSize: 9 }, axisLabel: { color: ECHART_DARK.text, fontSize: 9 }, splitLine: { show: false } },
      ],
      series: [
        { name: 'VIX', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 0, data: vix, lineStyle: { color: ECHART_DARK.warn }, itemStyle: { color: ECHART_DARK.warn } },
        { name: 'P/C', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, data: pc, lineStyle: { color: ECHART_DARK.accent }, itemStyle: { color: ECHART_DARK.accent } },
        { name: '散户热度', type: 'bar', yAxisIndex: 1, data: heat, itemStyle: { color: 'rgba(125, 211, 252, 0.35)' } },
      ],
    }
  }, [history])
  return <div ref={ref} className="h-32 w-full" />
}

export function MarketSentimentPanel({ vixData, sentimentInd, sentimentHistory }: { vixData: any; sentimentInd?: any; sentimentHistory?: any[] }) {
  const [showInfo, setShowInfo] = useState(false)

  // 贪婪恐惧指数由后端用真实行情因子合成（fear_greed.value），无数据时统一置空渲染 N/A。
  const fgScore: number | null = sentimentInd?.fear_greed?.value ?? null
  const fgStatus: string = sentimentInd?.fear_greed?.status ?? ''

  // 优先用后端下发的语义状态，无数据时降级为"暂无数据"；颜色按档位映射。
  let fgLabel = fgScore == null ? '暂无数据' : (fgStatus || '中性')
  let fgColor = 'text-muted-foreground'
  if (fgScore != null) {
    if (fgScore >= 75) { fgColor = 'text-[hsl(var(--bull))]' }
    else if (fgScore >= 55) { fgColor = 'text-[hsl(var(--bull))]' }
    else if (fgScore <= 25) { fgColor = 'text-[hsl(var(--bear))]' }
    else if (fgScore <= 45) { fgColor = 'text-[hsl(var(--bear))]' }
    else { fgColor = 'text-[hsl(var(--warn))]' }
  }

  // SENT-01 极端位标注：<20 极度恐惧 / >80 极度贪婪
  const fgExtreme = fgScore != null && (fgScore < 20 || fgScore > 80)
    ? (fgScore < 20 ? { text: '极度恐惧', cls: 'text-[hsl(var(--bear))]' } : { text: '极度贪婪', cls: 'text-[hsl(var(--bull))]' })
    : null

  const pcVal = sentimentInd?.pc_ratio?.value ?? null
  const pcStatus = sentimentInd?.pc_ratio?.status ?? 'N/A'
  const csVal = sentimentInd?.credit_spread?.value ?? null
  const csStatus = sentimentInd?.credit_spread?.status ?? 'N/A'

  // SENT-01：用真实历史序列绘制迷你 sparkline（无数据则空，不注入假数据）
  const vixSpark = (sentimentHistory || []).map(r => (r.vix != null ? Number(r.vix.toFixed(2)) : null)).filter(v => v != null) as number[]
  const pcSpark = (sentimentHistory || []).map(r => (r.pc_ratio != null ? Number(r.pc_ratio.toFixed(3)) : null)).filter(v => v != null) as number[]
  const csSpark = (sentimentHistory || []).map(r => (r.credit_spread != null ? Number(r.credit_spread.toFixed(2)) : null)).filter(v => v != null) as number[]

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
              {fgScore != null ? (
                <div className="opacity-60"><Sparkline data={[]} tone={fgScore >= 50 ? 'bull' : 'bear'} /></div>
              ) : (
                <div className="opacity-60 text-[10px] text-muted-foreground/50">暂无数据</div>
              )}
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className={cn('text-2xl font-bold font-mono tabular-nums leading-none transition-colors duration-500', fgColor)}>{fgScore ?? 'N/A'}</span>
              <span className={cn('text-[10px] font-bold uppercase transition-colors duration-500', fgColor)}>{fgLabel}</span>
            </div>
          </div>
          {fgExtreme && (
            <span className={cn('self-start text-[9px] font-bold px-1.5 py-0.5 rounded bg-secondary/40', fgExtreme.cls)}>⚠ {fgExtreme.text}（{fgScore}）</span>
          )}
          <div className="relative h-2 w-full rounded-full bg-gradient-to-r from-[hsl(var(--bear))] via-[hsl(var(--warn))] to-[hsl(var(--bull))] opacity-90 overflow-hidden">
             <div className="absolute top-0 bottom-0 w-1 bg-white shadow-[0_0_5px_rgba(255,255,255,1)] rounded-full transition-all duration-1000 ease-out" style={{ left: `${fgScore ?? 0}%`, transform: 'translateX(-50%)' }} />
          </div>
        </div>

        {/* SENT-01：情绪因子历史折线（真实数据，替代原有 mock sparkline） */}
        <div className="pt-1">
          <div className="text-[9px] text-muted-foreground font-semibold mb-1 flex items-center gap-1"><Activity className="h-3 w-3" /> 情绪因子历史趋势</div>
          {sentimentHistory && sentimentHistory.length > 0 ? (
            <SentimentHistoryChart history={sentimentHistory} />
          ) : (
            <div className="h-32 flex items-center justify-center text-[10px] text-muted-foreground/50">暂无历史序列</div>
          )}
        </div>

        <div className="flex flex-col gap-1.5 pt-3 border-t border-border/20">
          <div className="flex items-center justify-between"><span className="text-[10px] text-muted-foreground font-semibold flex items-center gap-1"><Activity className="h-3 w-3" /> 恐慌指数 (VIX)</span>{vixData && vixData.value != null ? (<div className="flex items-center gap-2"><div className="opacity-60"><Sparkline data={vixSpark} tone={(vixData.change ?? 0) <= 0 ? 'bull' : 'bear'} /></div><div className="flex items-baseline gap-1.5"><span className="text-sm font-bold font-mono tabular-nums">{vixData.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span><span className={cn('text-[10px] font-mono font-bold', (vixData.change ?? 0) >= 0 ? 'text-[hsl(var(--bear))]' : 'text-[hsl(var(--bull))]')}>{(vixData.change ?? 0) >= 0 ? '+' : ''}{(vixData.change ?? 0).toFixed(2)}%</span></div></div>) : (<span className="text-xs text-muted-foreground">--</span>)}</div>
          <div className="text-[9px] text-muted-foreground leading-relaxed mt-1">{vixData?.value < 15 ? '隐含波动率处于低位，市场风险偏好较高，单边或缓涨行情为主。' : vixData?.value > 25 ? '隐含波动率大幅飙升，避险情绪浓厚，警惕资产价格尾部风险。' : '波动率处于历史均值区间，多空博弈分歧加剧，市场呈震荡态势。'}</div>
          <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-border/10">
            <div className="flex flex-col gap-1"><div className="flex items-center justify-between"><span className="text-[9px] text-muted-foreground">期权 P/C Ratio</span><div className="opacity-60 scale-75 origin-right"><Sparkline data={pcSpark} tone={pcVal != null && pcVal < 1.0 ? 'bull' : 'bear'} /></div></div><span className="text-xs font-mono font-bold text-foreground -mt-1">{pcVal != null ? pcVal.toFixed(2) : '--'} <span className={cn('text-[8px] ml-1', pcVal != null && pcVal < 1.0 ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]')}>{pcStatus}</span></span></div>
            <div className="flex flex-col gap-1"><div className="flex items-center justify-between"><span className="text-[9px] text-muted-foreground">高收益债利差</span><div className="opacity-60 scale-75 origin-right"><Sparkline data={csSpark} tone={csVal != null && csVal < 4.5 ? 'bull' : 'bear'} /></div></div><span className="text-xs font-mono font-bold text-foreground -mt-1">{csVal != null ? csVal.toFixed(2) : '--'}% <span className={cn('text-[8px] ml-1', csVal != null && csVal < 4.5 ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]')}>{csStatus}</span></span></div>
          </div>
        </div>
      </div>
      {/* 底部数据更新提示（对齐 Figma 设计稿） */}
      <div className="px-3 py-1.5 border-t border-border/20 flex items-center text-[10px] text-muted-foreground/60">
        <span className="inline-block w-1 h-1 rounded-full bg-[hsl(var(--bull))]/70 mr-1.5" />
        更新于&nbsp;实时
      </div>
    </div>
  )
}
