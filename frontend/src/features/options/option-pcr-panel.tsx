import { useEffect, useState } from 'react'
import type { EChartsCoreOption } from 'echarts'
import { API_BASE_URL } from '@/lib/constants'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface SentimentPoint {
  timestamp: string
  vix_value: number | null
  pc_ratio: number | null
  credit_spread: number | null
  fear_greed_score: number | null
}

function pcrVerdict(pcr: number | null): { text: string; cls: string } {
  if (pcr == null || !isFinite(pcr)) return { text: '数据缺失', cls: 'text-slate-400' }
  if (pcr > 1.1) return { text: '极度看跌 (散户恐慌/对冲需求强)', cls: 'text-red-400' }
  if (pcr > 0.9) return { text: '偏空情绪', cls: 'text-amber-400' }
  if (pcr < 0.7) return { text: '极度看涨 (散户裸卖 PUT/追涨)', cls: 'text-emerald-400' }
  return { text: '中性情绪', cls: 'text-slate-300' }
}

export function OptionPcrPanel() {
  const [rows, setRows] = useState<SentimentPoint[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(`${API_BASE_URL}/macro/sentiment-history?limit=60`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) return r.json().then((err) => {
          throw new Error(err?.detail || `HTTP ${r.status}`)
        })
        return r.json()
      })
      .then((j) => {
        // 兼容：信封 {code,msg,data:{status,data:[...]}} → 取 data.data；老格式直接是数组
        if (!cancelled) setRows(Array.isArray(j) ? j : (j as any)?.data?.data ?? (j as any)?.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const buildOption = () => {
    if (!rows || !rows.length) return null
    const dates = rows.map((r) =>
      ((r as any).time || r.timestamp || '').replace('T', ' ').slice(0, 16),
    )
    const pcr = rows.map((r) => (r.pc_ratio != null ? Number(r.pc_ratio.toFixed(3)) : null))
    const vix = rows.map((r) =>
      ((r as any).vix ?? r.vix_value) != null
        ? Number(((r as any).vix ?? r.vix_value).toFixed(2))
        : null,
    )
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: ECHART_DARK.tooltipBg,
        borderColor: ECHART_DARK.split,
        textStyle: { color: '#e2e8f0' },
      },
      legend: {
        data: ['Put/Call Ratio', 'VIX'],
        textStyle: { color: ECHART_DARK.text },
        top: 4,
      },
      grid: { left: 52, right: 52, top: 44, bottom: 28 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: ECHART_DARK.split } },
        axisLabel: { color: ECHART_DARK.text, fontSize: 10 },
      },
      yAxis: [
        {
          type: 'value',
          name: 'P/C',
          position: 'left',
          nameTextStyle: { color: ECHART_DARK.primary },
          axisLabel: { color: ECHART_DARK.text },
          splitLine: { lineStyle: { color: ECHART_DARK.split } },
        },
        {
          type: 'value',
          name: 'VIX',
          position: 'right',
          nameTextStyle: { color: ECHART_DARK.warn },
          axisLabel: { color: ECHART_DARK.text },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Put/Call Ratio',
          type: 'line',
          yAxisIndex: 0,
          data: pcr,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: ECHART_DARK.primary, width: 2 },
          itemStyle: { color: ECHART_DARK.primary },
        },
        {
          name: 'VIX',
          type: 'line',
          yAxisIndex: 1,
          data: vix,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: ECHART_DARK.warn, width: 2 },
          itemStyle: { color: ECHART_DARK.warn },
        },
      ],
    } as EChartsCoreOption
  }

  const ref = useEChart(buildOption, [rows])
  const latest = rows && rows.length ? rows[rows.length - 1] : null
  const verdict = pcrVerdict(latest?.pc_ratio ?? null)

  if (loading) return <div className="p-6 text-sm text-slate-400">加载 Put/Call Ratio 情绪…</div>
  if (error) return <div className="p-6 text-sm text-red-400">情绪数据获取失败：{error}</div>
  if (!rows || !rows.length)
    return <div className="p-6 text-sm text-slate-400">暂无情绪历史数据（需 sentiment_tracker 落库后生效）</div>

  return (
    <div className="flex flex-col gap-3">
      {/* 头部：最新 PCR 数值 + 研判 + 实时标签（对齐 Figma 设计稿） */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] text-muted-foreground">最新 Put/Call Ratio</span>
          <span className={'text-2xl font-bold font-mono tabular-nums leading-none ' + verdict.cls}>
            {(latest?.pc_ratio ?? NaN).toFixed(2)}
          </span>
          <span className="flex items-center gap-1 text-[10px] font-bold text-[#10B981] dark:text-[#34D399] bg-[#34D399]/10 px-1.5 py-0.5 rounded">
            <span className="inline-block w-1 h-1 rounded-full bg-[#10B981] animate-pulse" />
            实时
          </span>
          <span className="text-[10px] text-muted-foreground ml-1">
            <span className="text-[#10B981] dark:text-[#34D399]">&gt;1 较高</span>
            <span className="mx-1.5 text-border">|</span>
            <span className="text-[#EF4444] dark:text-[#F87171]">&lt;1 偏低</span>
          </span>
        </div>
        <div className="hidden lg:block w-px h-5 bg-border/50" />
        <div className="rounded-lg border border-border/50 bg-card/40 px-3 py-1.5">
          <div className="text-[10px] text-slate-500">VIX 恐慌指数</div>
          <div className="text-sm font-semibold text-amber-300 tabular-nums">
            {(latest?.vix_value ?? NaN).toFixed(2)}
          </div>
        </div>
        <div className={'text-xs ' + verdict.cls}>{verdict.text}</div>
      </div>
      {/* 图例 + 折线图 */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-0.5 bg-[#10B981] dark:bg-[#34D399] rounded" />PCR · 60日</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-0.5 bg-amber-400 rounded" style={{borderTop: '1px dashed #f59e0b', background: 'transparent', height: '1px'}} />VIX</span>
      </div>
      <div ref={ref} className="h-[280px] w-full" />
      <div className="text-[11px] text-slate-500">
        PCR &gt; 1.0 通常反映看跌/对冲情绪升温；PCR &lt; 0.7 反映散户追涨、市场情绪过热。
        数据来源：市场级 Put/Call Ratio (CBOE ^CPC) 经 sentiment_tracker 真实落库。
      </div>
    </div>
  )
}
