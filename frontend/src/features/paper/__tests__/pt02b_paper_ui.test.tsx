/**
 * PT-02b: 纸面组合前端测试
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

// Mock apiClient
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: { data: [] } }),
    post: vi.fn().mockResolvedValue({ data: { status: 'success' } }),
  },
}))

// Mock lightweight-charts
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn().mockReturnValue({
    addSeries: vi.fn().mockReturnValue({
      setData: vi.fn(),
      setMarkers: vi.fn(),
    }),
    timeScale: vi.fn().mockReturnValue({
      fitContent: vi.fn(),
    }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    priceScale: vi.fn().mockReturnValue({
      applyOptions: vi.fn(),
    }),
  }),
  ColorType: { Solid: 'solid' },
  LineStyle: { Dashed: 1, Dotted: 2 },
  AreaSeries: 'AreaSeries',
  LineSeries: 'LineSeries',
  CandlestickSeries: 'CandlestickSeries',
  HistogramSeries: 'HistogramSeries',
}))

// ─── 列表页 ───

describe('PaperListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders list page header', async () => {
    const { PaperListPage } = await import('../page')
    render(
      <MemoryRouter>
        <PaperListPage />
      </MemoryRouter>
    )
    expect(screen.getByText('纸面组合')).toBeTruthy()
    expect(screen.getByText('创建组合')).toBeTruthy()
  })

  it('shows empty state when no portfolios', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: [] } } as any)

    const { PaperListPage } = await import('../page')
    render(
      <MemoryRouter>
        <PaperListPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('暂无纸面组合')).toBeTruthy()
    }, { timeout: 2000 })
  })

  it('renders portfolio rows', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        data: [
          {
            id: 'p1',
            name: '测试组合',
            strategy_name: 'momentum',
            market: 'HK',
            status: 'running',
            initial_capital: 100000,
            created_at: '2026-07-01T00:00:00Z',
          },
        ],
      },
    } as any)

    const { PaperListPage } = await import('../page')
    render(
      <MemoryRouter>
        <PaperListPage />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('测试组合')).toBeTruthy()
    }, { timeout: 2000 })
    expect(screen.getByText('momentum')).toBeTruthy()
    expect(screen.getByText('运行中')).toBeTruthy()
  })
})

// ─── 详情页 ───

describe('PortfolioDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders detail page with tabs', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockImplementation(((path: string) => {
      if (path.includes('/nav')) {
        return Promise.resolve({ data: { data: [] } } as any)
      }
      if (path.includes('/compare')) {
        return Promise.resolve({ data: { data: null } } as any)
      }
      return Promise.resolve({
        data: {
          data: {
            id: 'p1',
            name: '测试组合',
            strategy_name: 'momentum',
            market: 'HK',
            status: 'running',
            initial_capital: 100000,
            positions: [],
          },
        },
      } as any)
    }) as any)

    const { PortfolioDetail } = await import('../detail/portfolio-detail')
    render(
      <MemoryRouter initialEntries={['/paper/p1']}>
        <Routes>
          <Route path="/paper/:portfolioId" element={<PortfolioDetail />} />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('测试组合')).toBeTruthy()
    }, { timeout: 2000 })
    expect(screen.getByText('概览')).toBeTruthy()
    expect(screen.getByText('对比')).toBeTruthy()
    expect(screen.getByText('流水')).toBeTruthy()
  })

  it('shows not found when portfolio missing', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: null } } as any)

    const { PortfolioDetail } = await import('../detail/portfolio-detail')
    render(
      <MemoryRouter initialEntries={['/paper/missing']}>
        <Routes>
          <Route path="/paper/:portfolioId" element={<PortfolioDetail />} />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText('组合不存在或已删除')).toBeTruthy()
    }, { timeout: 2000 })
  })
})

// ─── 漂移面板 ───

describe('DriftPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows alert banner when TE exceeds threshold', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        data: {
          tracking_error: 0.20,
          cumulative_drift: 0.05,
          paper_sharpe: 1.5,
          paper_max_dd: -0.12,
        },
      },
    } as any)

    const { DriftPanel } = await import('../detail/drift-panel')
    render(
      <MemoryRouter>
        <DriftPanel portfolioId="p1" />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText(/纸面漂移告警/)).toBeTruthy()
    }, { timeout: 2000 })
    expect(screen.getByText(/TE 20.0%/)).toBeTruthy()
  })

  it('no alert when within threshold', async () => {
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        data: {
          tracking_error: 0.05,
          cumulative_drift: 0.02,
          paper_sharpe: 1.5,
          paper_max_dd: -0.08,
        },
      },
    } as any)

    const { DriftPanel } = await import('../detail/drift-panel')
    render(
      <MemoryRouter>
        <DriftPanel portfolioId="p1" />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.queryByText(/纸面漂移告警/)).toBeNull()
    }, { timeout: 2000 })
  })
})

// ─── 创建表单 ───

describe('CreatePortfolioDialog', () => {
  it('renders form fields', async () => {
    const { CreatePortfolioDialog } = await import('../create-portfolio-dialog')
    render(
      <MemoryRouter>
        <CreatePortfolioDialog onClose={() => {}} onCreated={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByText('创建纸面组合')).toBeTruthy()
    expect(screen.getByPlaceholderText('如：腾讯动量策略')).toBeTruthy()
    expect(screen.getByText('创建')).toBeTruthy()
  })
})
