/**
 * FIN-07 · 财报看板类型层（docs/28 §七）
 *
 * 后端 SSOT：routers/financials.py（统一响应 {status, message, data, timestamp}）。
 * 只打内网后端（取数统一走 useFinancialsData → apiClient），禁止直连外部数据源（AGENTS §2）。
 */

// ── statements 宽表 ──────────────────────────────────────────────
export type StatementKind = 'income' | 'balance' | 'cash'
export type StatementBasis = 'latest' | 'as_reported'

export interface StatementRow {
  concept: string
  label: string
  /** 与 periods 等长；缺失科目为 null（禁止补 0） */
  values: (number | null)[]
  common_size: (number | null)[]
  yoy: (number | null)[]
  derived: boolean[]
  restated: boolean[]
  check_failed: string[][]
}

export interface StatementView {
  entity_id: string
  statement: StatementKind
  periods: string[]
  rows: StatementRow[]
  basis: StatementBasis
  currency: string
  source_mix: Record<string, number>
  integrity: {
    failed_periods: string[]
    total_facts: number
    derived_facts: number
    restated_facts: number
  }
}

// ── analytics（FIN-05）──────────────────────────────────────────
export interface DupontPeriod {
  period: string
  roe: number | null
  factors: { net_margin: number | null; asset_turnover: number | null; equity_multiplier: number | null }
  roe_product: number | null
  factors_5: Record<string, number | null>
  roe_product_5: number | null
  check_failed: boolean
  asset_base: string
  equity_base: string
}

export interface RatioItem {
  cfo_to_net_income: number | null
  accruals_ratio: number | null
  fcf: number | null
  fcf_to_net_income: number | null
  fcf_margin: number | null
  capex_intensity: number | null
  asset_base: string
  missing: string[]
}

export interface ScoreItem {
  key: string
  name: string
  passed: boolean | null
}

export interface Piotroski {
  score: number
  max_score: number
  unknown: string[]
  items: ScoreItem[]
  missing: string[]
}

export interface AltmanZ {
  z: number | null
  zone: string
  thresholds: { safe: number; grey: number }
  components: Record<string, number | null>
  weights: Record<string, number>
  missing: string[]
}

export interface BeneishM {
  m: number | null
  flagged: boolean | null
  threshold: number
  coefficients: Record<string, number>
  intercept: number
  indices: Record<string, number | null>
  missing: string[]
}

export interface TtmPoint {
  label: string
  value: number
}

export interface AnalyticsView {
  latest_period: string
  dupont: DupontPeriod[]
  cash_flow_quality: RatioItem
  piotroski: Piotroski
  altman_z: AltmanZ
  beneish_m: BeneishM
  ttm: Record<'revenue' | 'net_income' | 'cfo', TtmPoint[]>
}

// ── peers（FIN-06）──────────────────────────────────────────────
export interface Aggregates {
  count: number
  median: number | null
  p25: number | null
  p75: number | null
  revenue_weighted?: number
}

/** FIN-09：同业明细行（升序），散点图数据支撑；本体由前端按 entity_id 高亮 */
export interface PeerRow {
  entity_id: string
  value: number
}

export interface PeersView {
  entity_id: string
  value: number
  sample_size: number
  insufficient: boolean
  percentile: number | null
  missing_peers: string[]
  aggregates: Aggregates
  peer_rows?: PeerRow[]
}

export interface PeersResponse extends PeersView {
  concept: string
  tag: string
  frame: string
  basis: 'market' | 'peers'
}

// ── filings / restatements ──────────────────────────────────────
export interface FilingItem {
  entity_id: string
  form_type: string
  fiscal_year: number | null
  filed_at: string | null
  accession_no: string
  doc_url: string | null
  lang: string | null
  rag_indexed: boolean
}

export interface RestatementItem extends FilingItem {
  concept: string
  label: string
  unit: string | null
  period_end: string | null
  value_as_reported: number | null
  value_latest: number | null
  filed_as_reported: string | null
  filed_latest: string | null
  delta: number | null
  delta_pct: number | null
}

// ── text layer（FIN-08b/08c · 文本层消费）────────────────────────
export interface TextDiffFilingRef {
  accession_no: string
  fiscal_year: number | null
  doc_url: string | null
}

export interface TextDiffFragment {
  op: string
  old: string
  new: string
}

export interface TextDiffSection {
  section: string
  status: 'rewritten' | 'similar' | 'missing'
  similarity?: number
  fragments?: TextDiffFragment[]
  missing_in?: 'old' | 'new'
}

export interface TextDiffView {
  entity_id: string
  old: TextDiffFilingRef
  new: TextDiffFilingRef
  sections: TextDiffSection[]
  rewritten: string[]
  missing: string[]
}

export interface IngestResult {
  entity_id: string
  accession_no: string
  doc_url: string
  chunks_written: number
}

export const FINANCIALS_PATHS = {
  statements: (entity: string) => `/financials/statements/${encodeURIComponent(entity)}`,
  analytics: (entity: string) => `/financials/analytics/${encodeURIComponent(entity)}`,
  peers: (entity: string) => `/financials/peers/${encodeURIComponent(entity)}`,
  filings: (entity: string) => `/financials/filings/${encodeURIComponent(entity)}`,
  restatements: (entity: string) => `/financials/restatements/${encodeURIComponent(entity)}`,
  textDiff: (entity: string) => `/financials/text/diff/${encodeURIComponent(entity)}`,
  ingestFiling: (entity: string, accession: string) =>
    `/financials/filings/${encodeURIComponent(entity)}/${encodeURIComponent(accession)}/ingest`,
} as const
