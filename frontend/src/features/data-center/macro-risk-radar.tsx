import { useMemo } from 'react'
import { Radio } from 'lucide-react'
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
      const cur = 'hsl(var(--bull))'
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
        {/* 顶部右侧切换按钮组：指标说明 / 算法（对齐 Figma 设计稿） */}
        <div className="ml-auto flex items-center bg-secondary/40 rounded-full p-0.5 text-[10px]">
          <button
            onClick={() => setRadarInfo(true)}
            className="px-2.5 py-0.5 rounded-full font-medium transition-colors bg-secondary text-foreground/90 shadow-sm"
          >
            指标说明
          </button>
          <button
            onClick={() => setRadarInfo(true)}
            className="px-2.5 py-0.5 rounded-full font-medium transition-colors text-muted-foreground hover:text-foreground"
          >
            算法
          </button>
        </div>
      </div>
      {radarInfo && <RadarInfoPanel radarData={radar} onClose={() => setRadarInfo(false)} />}
      <div className="p-1 h-44">
        <div ref={chartRef} className="w-full h-full" />
      </div>
      <div className="px-4 py-1.5 border-t border-border/20 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-[hsl(var(--bull))] rounded" />当前</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground/50" />基准</span>
        <span className="ml-auto text-[9px] text-muted-foreground italic">{'>'}70=乐观</span>
      </div>
    </div>
  )
}
