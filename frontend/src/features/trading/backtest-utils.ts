// 回测结果相关的纯计算工具（非 mock 数据）。
// 历史假数据常量已按 §14.1 移除：未运行回测时由调用方回落空数组并渲染 EmptyState，
// 不再在 PROD 下注入任何假净值曲线 / 假指标。

// 根据日收益率序列计算直方图（用于收益分布图）
export function computeHistogram(returns: number[], bins = 25) {
  if (returns.length === 0) return []
  const min = Math.min(...returns)
  const max = Math.max(...returns)
  const width = (max - min) / bins || 1
  const counts = new Array(bins).fill(0)
  for (const r of returns) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((r - min) / width)))
    counts[idx] += 1
  }
  const maxCount = Math.max(...counts)
  return counts.map((c, i) => ({
    bin: min + (i + 0.5) * width,
    count: c,
    freq: maxCount ? c / maxCount : 0,
  }))
}
