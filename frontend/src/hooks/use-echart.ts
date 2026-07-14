import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

/** Imperative ECharts lifecycle: init → setOption → resize → dispose. */
export function useEChart(
  buildOption: () => echarts.EChartsCoreOption | null,
  deps: unknown[],
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(containerRef.current)
    }
    const option = buildOption()
    if (option) instanceRef.current.setOption(option, true)

    const onResize = () => instanceRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    return () => {
      instanceRef.current?.dispose()
      instanceRef.current = null
    }
  }, [])

  return containerRef
}

export const ECHART_DARK = {
  text: '#94a3b8',
  split: '#1e293b',
  tooltipBg: '#1e293b',
  up: '#10b981',
  down: '#ef4444',
  primary: '#8b5cf6',
  accent: '#3b82f6',
  warn: '#f59e0b',
} as const
