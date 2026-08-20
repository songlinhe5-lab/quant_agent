import { useEffect, useState } from 'react'
import type { EChartsCoreOption } from 'echarts'
import { API_BASE_URL, SEMANTIC_COLORS } from '@/lib/constants'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'
import { cn } from '@/lib/utils'

interface SentimentPoint {
  timestamp: string
  vix_value: number | null
  pc_ratio: number | null
  credit_spread: number | null
  fear_greed_score: number | null
}

// 简化 verdict（对齐 Figma 设计稿：偏多/偏空/中性）
function pcrVerdict(pcr: number | null): { text: string; cls: string } {
  if (pcr == null || !isFinite(pcr)) return { text: '数据缺失', cls: 'text-slate-400' }
  if (pcr > 1.0) return { text: '偏空', cls: 'text-[hsl(var(--bear))]' }
  if (pcr < 1.0) return { text: '偏多', cls: 'text-[hsl(var(--bull))]' }
  return { text: '中性', cls: 'text-slate-300' }
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
      // 关闭 ECharts 内置 legend（设计稿图例由外部静态渲染，统一视觉与排版）
      legend: { show: false },
      grid: { left: 48, right: 48, top: 28, bottom: 24 },
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
          min: (val: { min: number }) => Math.min(val.min, 0.7),
          max: (val: { max: number }) => Math.max(val.max, 1.2),
          nameTextStyle: { color: SEMANTIC_COLORS.info },
          axisLabel: { color: ECHART_DARK.text, fontSize: 10 },
          splitLine: { lineStyle: { color: ECHART_DARK.split } },
        },
        {
          type: 'value',
          name: 'VIX',
          position: 'right',
          nameTextStyle: { color: SEMANTIC_COLORS.warn },
          axisLabel: { color: ECHART_DARK.text, fontSize: 10 },
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
          lineStyle: { color: 'hsl(var(--info))', width: 2 },
          itemStyle: { color: 'hsl(var(--info))' },
          // PCR=1 水平参考线（对齐 Figma 设计稿）
          markLine: {
            silent: true,
            symbol: 'none',
            label: {
              show: true,
              position: 'insideStartTop',
              color: '#94a3b8',
              fontSize: 10,
              formatter: 'PCR = 1',
              distance: 4,
            },
            lineStyle: { color: '#94a3b8', type: 'dashed', width: 1, opacity: 0.5 },
            data: [{ yAxis: 1 }],
          },
        },
        {
          name: 'VIX',
          type: 'line',
          yAxisIndex: 1,
          data: vix,
          smooth: true,
          showSymbol: false,
          // VIX 黄色虚线（对齐 Figma 设计稿）
          lineStyle: { color: 'hsl(var(--warn))', width: 1.5, type: 'dashed' },
          itemStyle: { color: 'hsl(var(--warn))' },
        },
      ],
    } as EChartsCoreOption
  }

  const ref = useEChart(buildOption, [rows])
  const latest = rows && rows.length ? rows[rows.length - 1] : null
  const verdict = pcrVerdict(latest?.pc_ratio ?? null)
  const isBullish = verdict.text === '偏多'

  if (loading) return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border/30">
        <h3 className="text-sm font-semibold text-foreground">PCR 期权情绪</h3>
        <span className="text-[11px] text-muted-foreground ml-2">期权波动率页迁入</span>
      </div>
      <div className="p-6 text-sm text-slate-400">加载 Put/Call Ratio 情绪…</div>
    </div>
  )
  if (error) return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border/30">
        <h3 className="text-sm font-semibold text-foreground">PCR 期权情绪</h3>
        <span className="text-[11px] text-muted-foreground ml-2">期权波动率页迁入</span>
      </div>
      <div className="p-6 text-sm text-red-400">情绪数据获取失败：{error}</div>
    </div>
  )
  if (!rows || !rows.length)
    return (
      <div className="glass-card rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border/30">
          <h3 className="text-sm font-semibold text-foreground">PCR 期权情绪</h3>
          <span className="text-[11px] text-muted-foreground ml-2">期权波动率页迁入</span>
        </div>
        <div className="p-6 text-sm text-slate-400">暂无情绪历史数据（需 sentiment_tracker 落库后生效）</div>
      </div>
    )

  return (
    <div className="glass-card rounded-lg overflow-hidden flex flex-col">
      {/* 标题区（对齐 Figma 设计稿） */}
      <div className="px-4 py-3 border-b border-border/30 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">PCR 期权情绪</h3>
        <span className="text-[11px] text-muted-foreground">期权波动率页迁入</span>
      </div>

      {/* 数据头部：大数字 + verdict 标签 + 阈值说明 */}
      <div className="px-4 pt-4 pb-2">
        <div className="flex items-baseline gap-3">
          <span className={'text-3xl font-bold font-mono tabular-nums leading-none ' + verdict.cls}>
            {(latest?.pc_ratio ?? NaN).toFixed(2)}
          </span>
          <span className={cn(
            'text-[10px] font-bold px-2 py-0.5 rounded',
            isBullish
              ? 'bg-[hsl(var(--bull))]/15 text-[hsl(var(--bull))]'
              : 'bg-[hsl(var(--bear))]/15 text-[hsl(var(--bear))]'
          )}>
            {verdict.text}
          </span>
          <span className="text-[11px] text-muted-foreground">
            <span className="text-[hsl(var(--bear))]">&gt;1 偏空</span>
            <span className="mx-1.5 text-border">·</span>
            <span className="text-[hsl(var(--bull))]">&lt;1 偏多</span>
          </span>
        </div>
      </div>

      {/* 图例（对齐设计稿：PCR · 60日 蓝实线 + VIX 黄虚线） */}
      <div className="px-4 pb-2 flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-0.5 bg-[hsl(var(--info))] rounded" />
          PCR · 60日
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3" style={{ borderTop: '1px dashed hsl(var(--warn))' }} />
          VIX
        </span>
      </div>

      {/* 折线图 */}
      <div ref={ref} className="h-[280px] w-full px-2" />

      {/* 底部 footer（对齐设计稿） */}
      <div className="px-4 py-2.5 border-t border-border/20 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>数据源:Futu · CBOE</span>
        <span className="flex items-center gap-1.5">
          更新于
          <span className="flex items-center gap-1 text-[hsl(var(--bull))] font-bold">
            <span className="inline-block w-1 h-1 rounded-full bg-[hsl(var(--bull))] animate-pulse" />
            实时
          </span>
        </span>
      </div>
    </div>
  )
}