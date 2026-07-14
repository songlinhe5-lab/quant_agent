import { useMemo } from 'react'
import { Radio, Info } from 'lucide-react'
import { useTheme } from 'next-themes'
import { RadarInfoPanel } from './event-panels'
import { useEChart, ECHART_DARK } from '@/hooks/use-echart'

export function MacroRiskRadar({
  radar,
  radarInfo,
  setRadarInfo,
}: {
  radar: any[]
  radarInfo: boolean
  setRadarInfo: (v: boolean) => void
}) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const indicators = useMemo(
    () => (radar || []).map((d) => ({ name: d.axis, max: 100 })),
    [radar],
  )
  const current = useMemo(() => (radar || []).map((d) => d.current), [radar])
  const benchmark = useMemo(() => (radar || []).map((d) => d.benchmark), [radar])

  const chartRef = useEChart(
    () => {
      if (!indicators.length) return null
      const text = isDark ? ECHART_DARK.text : '#64748b'
      const split = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'
      const cur = isDark ? '#0ecb81' : '#059669'
      return {
        backgroundColor: 'transparent',
        tooltip: {
          backgroundColor: isDark ? ECHART_DARK.tooltipBg : 'rgba(255,255,255,0.95)',
          borderColor: split,
          textStyle: { color: isDark ? '#f8fafc' : '#0f172a', fontSize: 11 },
        },
        radar: {
          indicator: indicators,
          splitLine: { lineStyle: { color: split } },
          axisName: { color: text, fontSize: 10 },
          splitArea: { show: false },
        },
        series: [
          {
            type: 'radar',
            data: [
              {
                name: '当前',
                value: current,
                lineStyle: { color: cur, width: 1.5 },
                areaStyle: { color: cur, opacity: 0.15 },
                itemStyle: { color: cur },
              },
              {
                name: '基准',
                value: benchmark,
                lineStyle: { color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)', type: 'dashed', width: 1 },
                areaStyle: { color: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)' },
                itemStyle: { color: text },
              },
            ],
          },
        ],
      }
    },
    [indicators, current, benchmark, isDark],
  )

  return (
    <div className="glass-card rounded-lg overflow-hidden relative">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <Radio className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">宏观风险雷达</span>
        <button onClick={() => setRadarInfo(true)} className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground bg-secondary/30 hover:bg-secondary/60 px-2 py-0.5 rounded-full">
          <Info className="h-3 w-3" /><span>算法</span>
        </button>
      </div>
      {radarInfo && <RadarInfoPanel radarData={radar} onClose={() => setRadarInfo(false)} />}
      <div className="p-1 h-44">
        <div ref={chartRef} className="w-full h-full" />
      </div>
      <div className="px-4 py-1.5 border-t border-border/20 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-[#059669] dark:bg-[#0ecb81] rounded" />当前</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground/50" />基准</span>
        <span className="ml-auto text-[9px] text-muted-foreground italic">{'>'}70=乐观</span>
      </div>
    </div>
  )
}
