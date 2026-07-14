import type { HistogramBin } from './returns-histogram-chart'

export function buildTearSheetMetrics(metrics: Record<string, any>) {
  return [
    { label: '总收益率', value: metrics.total_return || '--', dir: parseFloat(metrics.total_return) > 0 ? 1 : -1 },
    { label: '年化收益率', value: metrics.annualized_return || '--', dir: parseFloat(metrics.annualized_return) > 0 ? 1 : -1 },
    { label: '夏普比率', value: metrics.sharpe_ratio || '--', dir: parseFloat(metrics.sharpe_ratio) > 1 ? 1 : -1 },
    { label: '最大回撤', value: metrics.max_drawdown || '--', dir: -1 },
    { label: '胜率', value: metrics.win_rate || '--', dir: parseFloat(metrics.win_rate) > 50 ? 1 : -1 },
    { label: '盈亏比', value: metrics.profit_factor || '--', dir: parseFloat(metrics.profit_factor) > 1 ? 1 : -1 },
    { label: '总交易次数', value: String(metrics.total_trades || '--'), dir: 0 },
    { label: '摩擦成本', value: metrics.total_friction_cost || '--', dir: -1 },
  ]
}

export function computeDrawdownStats(equityCurve: any[] | undefined) {
  if (!equityCurve) return { data: [] as any[], maxDdPeriod: null as any, longestDrawdowns: [] as any[] }

  let maxEq = 0
  let currentPeakDate = ''
  let maxDd = 0
  let maxDdPeakDate = ''
  let maxDdTroughDate = ''
  const allDrawdowns: any[] = []
  let inDrawdown = false
  let currentDdStart = ''
  let currentDdTrough = ''
  let currentDdMaxDepth = 0

  const data = equityCurve.map((d: any) => {
    if (d.equity > maxEq) {
      maxEq = d.equity
      currentPeakDate = d.date
    }
    const dd = maxEq > 0 ? ((maxEq - d.equity) / maxEq) * 100 : 0
    if (dd > maxDd) {
      maxDd = dd
      maxDdPeakDate = currentPeakDate
      maxDdTroughDate = d.date
    }

    if (d.equity < maxEq) {
      if (!inDrawdown) {
        inDrawdown = true
        currentDdStart = currentPeakDate
        currentDdMaxDepth = dd
        currentDdTrough = d.date
      } else if (dd > currentDdMaxDepth) {
        currentDdMaxDepth = dd
        currentDdTrough = d.date
      }
    } else if (d.equity >= maxEq && inDrawdown) {
      const durationDays = Math.floor(
        (new Date(d.date).getTime() - new Date(currentDdStart).getTime()) / (1000 * 3600 * 24),
      )
      if (durationDays > 0) {
        allDrawdowns.push({
          start: currentDdStart,
          trough: currentDdTrough,
          end: d.date,
          depth: currentDdMaxDepth,
          duration: durationDays,
          recovered: true,
        })
      }
      inDrawdown = false
      currentDdMaxDepth = 0
    }

    return { date: d.date, dd: -dd }
  })

  if (inDrawdown && data.length > 0) {
    const lastDate = equityCurve[equityCurve.length - 1].date
    const durationDays = Math.floor(
      (new Date(lastDate).getTime() - new Date(currentDdStart).getTime()) / (1000 * 3600 * 24),
    )
    if (durationDays > 0) {
      allDrawdowns.push({
        start: currentDdStart,
        trough: currentDdTrough,
        end: lastDate,
        depth: currentDdMaxDepth,
        duration: durationDays,
        recovered: false,
      })
    }
  }

  const longestDrawdowns = [...allDrawdowns].sort((a, b) => b.duration - a.duration).slice(0, 5)

  let recoveryDate = ''
  const peakEq = equityCurve.find((d: any) => d.date === maxDdPeakDate)?.equity || 0
  if (peakEq > 0 && maxDdTroughDate) {
    let pastTrough = false
    for (const d of equityCurve) {
      if (d.date === maxDdTroughDate) pastTrough = true
      if (pastTrough && d.date !== maxDdTroughDate && d.equity >= peakEq) {
        recoveryDate = d.date
        break
      }
    }
  }

  return {
    data,
    maxDdPeriod:
      maxDd > 0
        ? {
            start: maxDdPeakDate,
            trough: maxDdTroughDate,
            end: recoveryDate || data[data.length - 1].date,
            maxDdValue: -maxDd,
          }
        : null,
    longestDrawdowns,
  }
}

export function computeReturnsHistogram(equityCurve: any[] | undefined): HistogramBin[] {
  const defaultData: HistogramBin[] = [
    { range: '< -5%', count: 0, color: '#f87171', lightColor: '#dc2626' },
    { range: '-5~-3%', count: 0, color: '#fca5a5', lightColor: '#ef4444' },
    { range: '-3~-1%', count: 0, color: '#fcd34d', lightColor: '#f59e0b' },
    { range: '-1~0%', count: 0, color: '#d1d5db', lightColor: '#9ca3af' },
    { range: '0~1%', count: 0, color: '#6ee7b7', lightColor: '#10b981' },
    { range: '1~3%', count: 0, color: '#34d399', lightColor: '#059669' },
    { range: '3~5%', count: 0, color: '#10b981', lightColor: '#047857' },
    { range: '> 5%', count: 0, color: '#059669', lightColor: '#064e3b' },
  ]

  if (!equityCurve || equityCurve.length < 2) return defaultData

  const counts = [0, 0, 0, 0, 0, 0, 0, 0]
  const totalDays = equityCurve.length - 1

  for (let i = 1; i < equityCurve.length; i++) {
    const prevEq = equityCurve[i - 1].equity
    const currEq = equityCurve[i].equity
    if (prevEq > 0) {
      const retPct = ((currEq - prevEq) / prevEq) * 100
      if (retPct < -5) counts[0]++
      else if (retPct < -3) counts[1]++
      else if (retPct < -1) counts[2]++
      else if (retPct < 0) counts[3]++
      else if (retPct < 1) counts[4]++
      else if (retPct < 3) counts[5]++
      else if (retPct < 5) counts[6]++
      else counts[7]++
    }
  }

  return defaultData.map((item, idx) => ({
    ...item,
    count: counts[idx],
    percent: totalDays > 0 ? Number(((counts[idx] / totalDays) * 100).toFixed(1)) : 0,
  }))
}
