export type DataViewStatus = 'loading' | 'ready' | 'stale' | 'empty'

/**
 * 由 loading / empty / stale 布尔推导状态。
 * 独立成文件，避免与 DataState 组件同文件导出导致的 fast-refresh 警告。
 */
export function resolveDataStatus(opts: {
  loading?: boolean
  empty?: boolean
  stale?: boolean
}): DataViewStatus {
  if (opts.loading) return 'loading'
  if (opts.empty) return 'empty'
  if (opts.stale) return 'stale'
  return 'ready'
}
