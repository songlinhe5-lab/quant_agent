/**
 * 回测模块 Mock 数据 & 工具函数
 */

export const equityCurve = Array.from({ length: 60 }, (_, i) => ({
  t: i,
  strategy: 100000 + i * 2000 + Math.sin(i * 0.4) * 8000 + Math.random() * 3000,
  benchmark: 100000 + i * 1000 + Math.sin(i * 0.2) * 3000,
}))

export const underwaterData = Array.from({ length: 60 }, (_, i) => ({
  t: i,
  dd: -Math.abs(Math.sin(i * 0.15) * 12 + Math.random() * 3),
}))

export const returnsHist = [
  { range: '< -5%',  count: 12,  color: '#f87171', lightColor: '#dc2626' },
  { range: '-5~-3%', count: 28,  color: '#fca5a5', lightColor: '#ef4444' },
  { range: '-3~-1%', count: 67,  color: '#fcd34d', lightColor: '#f59e0b' },
  { range: '-1~0%',  count: 89,  color: '#d1d5db', lightColor: '#9ca3af' },
  { range: '0~1%',   count: 156, color: '#6ee7b7', lightColor: '#10b981' },
  { range: '1~3%',   count: 412, color: '#34d399', lightColor: '#059669' },
  { range: '3~5%',   count: 234, color: '#10b981', lightColor: '#047857' },
  { range: '> 5%',   count: 58,  color: '#059669', lightColor: '#064e3b' },
]

export const tearSheetMetrics = [
  { label: '年化收益率', value: '24.5%',  dir: 1,  note: '总收益 +124.5%' },
  { label: '夏普比率',   value: '2.34',   dir: 1,  note: '基准: > 1.0' },
  { label: '卡玛比率',   value: '1.98',   dir: 1,  note: '收益/最大回撤' },
  { label: '最大回撤',   value: '-12.3%', dir: -1, note: '持续 47 天' },
  { label: '胜率',       value: '62.1%',  dir: 1,  note: '盈亏比: 1.8x' },
  { label: '总交易次数', value: '1,247',  dir: 0,  note: '均持仓: 2.3天' },
  { label: 'Sortino',    value: '3.12',   dir: 1,  note: '仅负回报波动' },
  { label: 'Omega',      value: '1.72',   dir: 1,  note: '>1.0 为正期望' },
]

// 💡 将连续的 Float 数组 (如 Monte Carlo 的 raw_returns) 分箱为离散的直方图数据
export function computeHistogram(rawReturns: number[], binsCount = 30) {
  if (!rawReturns || rawReturns.length === 0) return []
  const min = Math.min(...rawReturns)
  const max = Math.max(...rawReturns)
  const step = (max - min) / binsCount

  const bins = Array.from({ length: binsCount }, (_, i) => {
    const rangeMin = min + i * step
    const rangeMax = min + (i + 1) * step
    return {
      rangeMin, rangeMax, count: 0,
      range: `${(rangeMin * 100).toFixed(1)}%~${(rangeMax * 100).toFixed(1)}%`,
      color: rangeMax <= 0 ? '#f87171' : rangeMin >= 0 ? '#34d399' : '#9ca3af',
      lightColor: rangeMax <= 0 ? '#dc2626' : rangeMin >= 0 ? '#059669' : '#4b5563',
    }
  })

  rawReturns.forEach(r => {
    let index = Math.floor((r - min) / step)
    if (index >= binsCount) index = binsCount - 1
    if (index < 0) index = 0
    bins[index].count++
  })

  return bins
}
