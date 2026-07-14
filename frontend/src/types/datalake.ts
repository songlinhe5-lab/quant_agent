/**
 * DQ-03e 数据湖快照类型（FE-PROD-04）
 */

export interface DataLakeSnapshot {
  snapshot_id: string
  as_of_date: string | null
  status: string
  manifest_hash: string | null
  ticker_count: number | null
  total_bytes: number | null
  is_monthly_anchor: boolean
  storage_tier: string | null
  published_at: string | null
  age_days?: number
  stale_warning?: boolean
}

/** 回测报告可复现性徽章（BT-02 / FE-PROD-04） */
export interface ReproducibilityBadge {
  code_hash: string
  manifest_hash: string | null
  reproducible: boolean
  data_snapshot_id?: string | null
  data_mode?: string
}

export const LATEST_PUBLISHED = 'latest_published'
export const LIVE_SNAPSHOT = 'live'
