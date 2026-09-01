/**
 * FIN-07：财报看板七组件 + 工作台测试（docs/28 §七）
 * 禁打真实后端：apiClient 全 mock；AG Grid / ECharts 用桩防 jsdom 无 canvas。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api-client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('ag-grid-community', () => ({
  AllCommunityModule: {},
  ModuleRegistry: { registerModules: vi.fn() },
  createGrid: vi.fn(() => ({ destroy: vi.fn(), setGridAriaProperty: vi.fn() })),
}))

vi.mock('@/hooks/use-echart', () => ({
  useEChart: () => ({ current: null }),
  ECHART_DARK: {
    text: '#94a3b8', split: '#1e293b', tooltipBg: '#1e293b',
    up: '#10b981', down: '#ef4444', primary: '#8b5cf6', accent: '#3b82f6', warn: '#f59e0b',
  },
}))

import { apiClient } from '@/lib/api-client'
import { FinancialsWorkbench } from '../financials-workbench'
import { StatementGrid } from '../statement-grid'
import { TrendChart } from '../trend-chart'
import { DupontPanel } from '../dupont-panel'
import { PeerCompare } from '../peer-compare'
import { QualityScorecard } from '../quality-scorecard'
import { FilingTimeline } from '../filing-timeline'
import { MdaDiffPanel } from '../mda-diff-panel'
import { RestatementDiff } from '../restatement-diff'

const getMock = vi.mocked(apiClient.get)
const postMock = vi.mocked(apiClient.post)

const ENTITY = 'US:CIK0000320193'

const STATEMENT_VIEW = {
  entity_id: ENTITY,
  statement: 'income',
  periods: ['FY2024', 'FY2025'],
  rows: [
    {
      concept: 'revenue', label: '营业收入',
      values: [100.0, 120.0], common_size: [100.0, 100.0], yoy: [null, 20.0],
      derived: [false, false], restated: [false, true],
      check_failed: [[], ['balance_check']],
    },
  ],
  basis: 'latest',
  currency: 'USD',
  source_mix: { sec: 12 },
  integrity: { failed_periods: ['FY2025'], total_facts: 12, derived_facts: 1, restated_facts: 1 },
}

const ANALYTICS_VIEW = {
  latest_period: 'FY2025',
  dupont: [
    {
      period: 'FY2025', roe: 0.264,
      factors: { net_margin: 0.22, asset_turnover: 0.75, equity_multiplier: 1.6 },
      roe_product: 0.264, factors_5: { tax_burden: 0.8, interest_burden: 0.95, operating_margin: 0.3, net_margin: 0.22, asset_turnover: 0.75, equity_multiplier: 1.6 },
      roe_product_5: 0.264, check_failed: false, asset_base: 'ending', equity_base: 'ending',
    },
  ],
  cash_flow_quality: {
    cfo_to_net_income: 1.1, accruals_ratio: -0.05, fcf: 90.0,
    fcf_to_net_income: 0.75, fcf_margin: 0.15, capex_intensity: 0.08, asset_base: 'ending', missing: [],
  },
  piotroski: {
    score: 7, max_score: 9, unknown: [],
    items: [{ key: 'roa', name: '资产回报率上升', passed: true }],
    missing: [],
  },
  altman_z: {
    z: 5.84, zone: 'safe', thresholds: { safe: 2.99, grey: 1.81 },
    components: { wc_ta: 0.2 }, weights: { wc_ta: 1.2 }, missing: [],
  },
  beneish_m: { m: -2.1, flagged: false, threshold: -2.22, coefficients: { dsri: 0.92 }, intercept: -4.84, indices: { dsri: 0.9 }, missing: [] },
  ttm: {
    revenue: [{ label: 'FY2025 Q1 TTM', value: 500 }],
    net_income: [{ label: 'FY2025 Q1 TTM', value: 110 }],
    cfo: [{ label: 'FY2025 Q1 TTM', value: 150 }],
  },
}

const PEERS_VIEW = {
  entity_id: ENTITY, concept: 'revenue', tag: 'Revenues', frame: 'CY2025', basis: 'market',
  value: 400.0, sample_size: 10, insufficient: false, percentile: 55.0,
  missing_peers: [], aggregates: { count: 10, median: 550.0, p25: 300.0, p75: 700.0, revenue_weighted: 610.0 },
}

const FILINGS = {
  count: 1,
  items: [{
    entity_id: ENTITY, form_type: '10-K', fiscal_year: 2025, filed_at: '2026-02-01T00:00:00Z',
    accession_no: '0000320193-26-000001', doc_url: 'https://example/doc.htm', lang: 'en', rag_indexed: true,
  }],
}

const RESTATEMENTS = {
  count: 1,
  items: [{
    ...FILINGS.items[0], concept: 'revenue', label: '营业收入', unit: 'USD', period_end: '2025-12-31',
    value_as_reported: 100.0, value_latest: 120.0,
    filed_as_reported: '2026-02-01', filed_latest: '2026-05-01', delta: 20.0, delta_pct: 0.2,
  }],
}

/** 按路径分发 mock 响应 */
function mockApi(paths: Record<string, { data: unknown } | Error>) {
  getMock.mockImplementation((path: string) => {
    const hit = Object.entries(paths).find(([k]) => path.startsWith(k))
    if (!hit) return Promise.reject(new Error(`mock 未覆盖: ${path}`))
    return hit[1] instanceof Error ? Promise.reject(hit[1]) : Promise.resolve(hit[1])
  })
}

beforeEach(() => {
  getMock.mockReset()
})
afterEach(cleanup)

function wrap(ui: React.ReactElement) {
  return <MemoryRouter initialEntries={['/financials']}>{ui}</MemoryRouter>
}

// ── hook 行为（经组件验证）────────────────────────────────────

describe('StatementGrid', () => {
  it('加载失败 → EmptyState 展示原因', async () => {
    mockApi({ '/financials/statements/': new Error('fin_entity_not_found: 无事实') })
    render(<StatementGrid entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('报表加载失败')).toBeTruthy())
  })

  it('有数据 → 渲染表格与口径切换（切换触发新请求），勾稽失败标红', async () => {
    mockApi({ '/financials/statements/': { data: STATEMENT_VIEW } })
    render(<StatementGrid entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('statement-grid')).toBeTruthy())
    expect(getMock).toHaveBeenCalledWith(
      expect.stringContaining('/financials/statements/'),
      { statement: 'income', basis: 'latest' },
    )
    // 勾稽失败提示（integrity.failed_periods 非空）
    expect(screen.getByText(/勾稽失败/)).toBeTruthy()
    // 口径切换 → 重新请求 as_reported
    fireEvent.click(screen.getByText('首次披露'))
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        expect.stringContaining('/financials/statements/'),
        { statement: 'income', basis: 'as_reported' },
      ),
    )
  })

  it('无数据且非加载中 → 空态引导回填', async () => {
    getMock.mockRejectedValue(Object.assign(new Error('x')))
    render(<StatementGrid entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('报表加载失败')).toBeTruthy())
  })
})

describe('TrendChart / DupontPanel', () => {
  it('无 TTM → 空态；有数据 → 图容器 + 净利率副轴', async () => {
    mockApi({ '/financials/analytics/': { data: ANALYTICS_VIEW } })
    render(<TrendChart entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('trend-chart')).toBeTruthy())
    expect(screen.getByText(/最新年报 FY2025/)).toBeTruthy()
  })

  it('Dupont 三/五因子切换', async () => {
    mockApi({ '/financials/analytics/': { data: ANALYTICS_VIEW } })
    render(<DupontPanel entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('dupont-chart')).toBeTruthy())
    expect(screen.getByText(/ROE 26\.4%/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('dupont-toggle'))
    expect(screen.getByText('五因子')).toBeTruthy()
  })
})

describe('PeerCompare', () => {
  it('样本不足 → 禁出分位结论的空态', async () => {
    mockApi({
      '/financials/peers/': {
        data: { ...PEERS_VIEW, insufficient: true, percentile: null, sample_size: 6, aggregates: { count: 6, median: 1, p25: 1, p75: 2 } },
      },
    })
    render(<PeerCompare entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('同业样本不足')).toBeTruthy())
    expect(screen.getByText(/仅 6 家/)).toBeTruthy()
  })

  it('正常截面 → 分位 + 区间带 + 缺席同业提示', async () => {
    mockApi({
      '/financials/peers/': { data: { ...PEERS_VIEW, missing_peers: ['US:CIK0009999999'] } },
    })
    render(<PeerCompare entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('55.0%')).toBeTruthy())
    expect(screen.getByTestId('peer-band')).toBeTruthy()
    expect(screen.getByText(/US:CIK0009999999/)).toBeTruthy()
    // peer_set 输入随请求透传
    fireEvent.change(screen.getByPlaceholderText(/peer_set/), { target: { value: 'MSFT, GOOG' } })
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(expect.stringContaining('/financials/peers/'), {
        concept: 'revenue',
        peer_set: 'MSFT, GOOG',
      }),
    )
  })

  it('FIN-09：明细行 → 散点渲染（本体高亮，不再降级区间条）', async () => {
    mockApi({
      '/financials/peers/': {
        data: {
          ...PEERS_VIEW,
          peer_rows: [
            { entity_id: ENTITY, value: 100 },
            { entity_id: 'US:CIK0000900002', value: 500 },
            { entity_id: 'US:CIK0000900003', value: 900 },
          ],
        },
      },
    })
    render(<PeerCompare entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('peer-scatter')).toBeTruthy())
    expect(screen.queryByTestId('peer-band')).toBeNull()
  })
})

describe('QualityScorecard', () => {
  it('三分 + 分项 + 阈值全部可见（禁黑箱总分）', async () => {
    mockApi({ '/financials/analytics/': { data: ANALYTICS_VIEW } })
    render(<QualityScorecard entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('Piotroski F-Score')).toBeTruthy())
    expect(screen.getByText((_, el) => el?.textContent === '7/9')).toBeTruthy()
    expect(screen.getByText(/阈值 safe 2\.99/)).toBeTruthy()
    expect(screen.getByText(/阈值 -2\.22/)).toBeTruthy()
    expect(screen.getByText(/CFO \/ 净利润/)).toBeTruthy()
  })
})

const TEXT_DIFF = {
  entity_id: ENTITY,
  old: { accession_no: '0000320193-24-000001', fiscal_year: 2024, doc_url: 'https://example/old.htm' },
  new: { accession_no: '0000320193-26-000001', fiscal_year: 2025, doc_url: 'https://example/new.htm' },
  sections: [
    { section: 'mda', status: 'rewritten', similarity: 0.72, fragments: [{ op: 'replace', old: 'Revenue grew 5%', new: 'Revenue grew 12%' }] },
    { section: 'risk_factors', status: 'similar', similarity: 0.95, fragments: [] },
    { section: 'quantitative_qualitative', status: 'missing', missing_in: 'new' },
  ],
  rewritten: ['mda'],
  missing: ['quantitative_qualitative'],
}

const FILINGS_NOT_INDEXED = {
  count: 1,
  items: [{ ...FILINGS.items[0], rag_indexed: false }],
}

describe('MdaDiffPanel', () => {
  it('重写章节排前标 amber，变化片段 old 删红 / new 增绿', async () => {
    mockApi({ '/financials/text/diff/': { data: TEXT_DIFF } })
    render(<MdaDiffPanel entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('mda-diff')).toBeTruthy())
    expect(screen.getByText(/重写章节：mda/)).toBeTruthy()
    expect(screen.getByText('- Revenue grew 5%')).toBeTruthy()
    expect(screen.getByText('+ Revenue grew 12%')).toBeTruthy()
    expect(screen.getByText('单侧缺失')).toBeTruthy()
  })

  it('加载失败 → EmptyState 展示原因', async () => {
    mockApi({ '/financials/text/diff/': new Error('不足两份 10-K') })
    render(<MdaDiffPanel entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('文本 diff 加载失败')).toBeTruthy())
  })
})

describe('FilingTimeline / RestatementDiff', () => {
  it('时间轴渲染申报与原文链接、RAG 状态', async () => {
    mockApi({ '/financials/filings/': { data: FILINGS } })
    render(<FilingTimeline entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('10-K')).toBeTruthy())
    expect(screen.getByText('RAG 已索引')).toBeTruthy()
    expect(screen.getByText('原文')).toBeTruthy()
  })

  it('重述 diff 表格渲染，相对差标红', async () => {
    mockApi({ '/financials/restatements/': { data: RESTATEMENTS } })
    render(<RestatementDiff entity={ENTITY} />)
    await waitFor(() => expect(screen.getByTestId('restatement-grid')).toBeTruthy())
    expect(screen.getByText(/重述科目 1 条/)).toBeTruthy()
  })

  it('未索引申报展示「送 RAG」，成功后回写状态与片段数', async () => {
    mockApi({ '/financials/filings/': { data: FILINGS_NOT_INDEXED } })
    postMock.mockResolvedValue({
      status: 'success',
      message: 'ok',
      data: { entity_id: ENTITY, accession_no: FILINGS.items[0].accession_no, doc_url: 'https://example/doc.htm', chunks_written: 12 },
    })
    render(<FilingTimeline entity={ENTITY} />)
    await waitFor(() => expect(screen.getByText('RAG 未索引')).toBeTruthy())
    expect(screen.getByTestId(`send-rag-${FILINGS.items[0].accession_no}`)).toBeTruthy()

    fireEvent.click(screen.getByTestId(`send-rag-${FILINGS.items[0].accession_no}`))
    await waitFor(() => expect(screen.getByText('+12 片段')).toBeTruthy())
    // entity 里的冒号会被 encodeURIComponent（api.ts 统一编码）
    expect(postMock).toHaveBeenCalledWith(
      expect.stringContaining(`/${FILINGS.items[0].accession_no}/ingest`),
    )
    expect(screen.queryByTestId(`send-rag-${FILINGS.items[0].accession_no}`)).toBeNull()  // 已索引，按钮消失
  })
})

describe('FinancialsWorkbench', () => {
  it('无 entity → InitOverlay 引导；输入后进 tab 并写 URL', async () => {
    mockApi({ '/financials/statements/': { data: STATEMENT_VIEW } })
    render(wrap(<FinancialsWorkbench />))
    expect(screen.getByText(/输入实体以加载财报/)).toBeTruthy()

    fireEvent.change(screen.getByTestId('entity-input'), { target: { value: 'aapl' } })
    fireEvent.submit(screen.getByTestId('entity-input').closest('form')!)

    await waitFor(() => expect(screen.getByText('AAPL')).toBeTruthy()) // 大写归一（ticker→CIK 由后端做）
    expect(screen.getByTestId('tab-statements')).toBeTruthy()
  })

  it('tab 切换加载对应组件（quality → analytics 请求）', async () => {
    mockApi({
      '/financials/statements/': { data: STATEMENT_VIEW },
      '/financials/analytics/': { data: ANALYTICS_VIEW },
    })
    render(
      <MemoryRouter initialEntries={['/financials?entity=aapl&tab=quality']}>
        <FinancialsWorkbench />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Piotroski F-Score')).toBeTruthy())
    expect(getMock).toHaveBeenCalledWith(
      expect.stringContaining('/financials/analytics/'),
      undefined,
    )
  })
})
