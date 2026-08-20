import { cn } from '@/lib/utils'

interface SparklineProps {
  data: number[]
  /** 线条颜色，默认跟随涨/跌语义 */
  tone?: 'bull' | 'bear' | 'auto' | 'muted'
  className?: string
  width?: number
  height?: number
  strokeWidth?: number
}

/**
 * 微型趋势线（设计稿市场脉搏表格内 sparkline）。
 * 纯 SVG 单色路径，无网格/无坐标轴，贴近终端极简观感。
 */
export function Sparkline({
  data,
  tone = 'auto',
  className,
  width = 56,
  height = 24,
  strokeWidth = 1.5,
}: SparklineProps) {
  if (!data || data.length < 2) {
    return <svg className={cn('sparkline', className)} viewBox={`0 0 ${width} ${height}`} />
  }

  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const stepX = width / (data.length - 1)
  const points = data.map((v, i) => {
    const x = i * stepX
    const y = height - ((v - min) / span) * (height - strokeWidth * 2) - strokeWidth
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const up = data[data.length - 1] >= data[0]
  const color =
    tone === 'bull'
      ? 'hsl(var(--bull))'
      : tone === 'bear'
        ? 'hsl(var(--bear))'
        : tone === 'muted'
          ? 'hsl(220 9% 46%)'
          : up
            ? 'hsl(var(--bull))'
            : 'hsl(var(--bear))'

  return (
    <svg
      className={cn('sparkline', className)}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="trend"
    >
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
