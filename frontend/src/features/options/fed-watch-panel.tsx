import { useEffect, useState } from 'react'
import type { EChartsCoreOption } from 'echarts'
import { apiClient } from '@/lib/api-client'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

interface FedMeeting {
  date?: string
  label?: string
  implied_rate?: number
  probability?: number
}

interface FedWatchData {
  next_meeting_implied_rate?: number
  policy_slope?: string
  meetings?: FedMeeting[]
  source?: string
  note?: string
}

function slopeTone(s?: string): string {
  if (s === 'hawkish') return 'text-red-400'
  if (s === 'dovish') return 'text-emerald-400'
  return 'text-amber-400'
}

function slopeText(s?: string): string {
  if (s === 'hawkish') return '鹰派（隐含加息/降息概率下降）'
  if (s === 'dovish') return '鸽派（隐含降息概率上升）'
  return '中性（政策路径平稳）'
}

export function FedWatchPanel() {
  const [data, setData] = useState<FedWatchData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiClient
      .get<{ data: FedWatchData }>('/macro/fed-watch')
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const buildOption = (): EChartsCoreOption | null => {
    if (!data?.meetings || !data.meetings.length) return null
    const labels = data.meetings.map((m) => m.date || m.label || '')
    const rates = data.meetings.map((m) => (m.implied_rate != null ? Number(m.implied_rate.toFixed(2)) : null))
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: ECHART_DARK.tooltipBg, borderColor: ECHART_DARK.split, textStyle: { color: '#e2e8f0' } },
      grid: { left: 48, right: 16, top: 24, bottom: 36 },
      xAxis: {
        type: 'category',
        data: labels,
        axisLine: { lineStyle: { color: ECHART_DARK.split } },
        axisLabel: { color: ECHART_DARK.text, fontSize: 10, rotate: 30 },
      },
      yAxis: {
        type: 'value',
        name: '隐含利率 %',
        nameTextStyle: { color: ECHART_DARK.text },
        axisLabel: { color: ECHART_DARK.text },
        splitLine: { lineStyle: { color: ECHART_DARK.split } },
      },
      series: [
        {
          type: 'line',
          step: 'middle',
          data: rates,
          smooth: false,
          showSymbol: true,
          symbolSize: 6,
          lineStyle: { color: ECHART_DARK.warn, width: 2 },
          itemStyle: { color: ECHART_DARK.warn },
          areaStyle: { color: 'rgba(245,158,11,0.12)' },
        },
      ],
    } as EChartsCoreOption
  }

  const ref = useEChart(buildOption, [data])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载 FedWatch 面板…</div>
  if (error) return <div className="p-6 text-sm text-red-400">FedWatch 数据获取失败：{error}</div>
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无 FedWatch 数据</div>

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">FedWatch 利率路径</span>
        {data.policy_slope && (
          <span className={'ml-auto text-[10px] font-mono font-bold ' + slopeTone(data.policy_slope)}>
            {slopeText(data.policy_slope)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 p-3">
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">下次会议隐含利率</div>
          <div className="text-lg font-semibold font-mono text-[#f59e0b]">
            {data.next_meeting_implied_rate != null ? data.next_meeting_implied_rate.toFixed(2) + '%' : '--'}
          </div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">政策斜率</div>
          <div className={'text-lg font-semibold font-mono ' + slopeTone(data.policy_slope)}>
            {data.policy_slope ? data.policy_slope.toUpperCase() : '--'}
          </div>
        </div>
      </div>
      <div ref={ref} className="h-[260px] w-full px-2 pb-2" />
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu FedWatch'} · 隐含利率为联邦基金期货定价推导，非 FOMC 点阵图
      </div>
    </div>
  )
}
