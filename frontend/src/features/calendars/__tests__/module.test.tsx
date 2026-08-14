/**
 * FE-PROD-05d：CalendarsModule 渲染与 Tab 切换测试 + utils 纯函数测试
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import {
  filterVisibleCategories,
  formatTimeInZone,
  categoryAnchorId,
  type CalendarCategoryView,
} from '../utils'

// Mock apiClient
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

import { apiClient } from '@/lib/api-client'

// ─── utils 纯函数 ─────────────────────────────────────────────
const SAMPLE_CATS: CalendarCategoryView[] = [
  {
    category: 'us_markets',
    display_name: 'US Markets',
    is_market_open: true,
    next_session_change: null,
    tiles: [],
  },
  {
    category: 'crypto',
    display_name: 'Crypto',
    is_market_open: true,
    next_session_change: null,
    tiles: [],
  },
]

describe('filterVisibleCategories', () => {
  it('无隐藏清单时返回全部类目', () => {
    expect(filterVisibleCategories(SAMPLE_CATS, [])).toHaveLength(2)
  })
  it('隐藏类目被过滤', () => {
    const res = filterVisibleCategories(SAMPLE_CATS, ['crypto'])
    expect(res).toHaveLength(1)
    expect(res[0].category).toBe('us_markets')
  })
})

describe('formatTimeInZone', () => {
  it('null 返回占位符', () => {
    expect(formatTimeInZone(null, 'Asia/Hong_Kong')).toBe('--')
  })
  it('非法字符串返回占位符', () => {
    expect(formatTimeInZone('not-a-date', 'Asia/Hong_Kong')).toBe('--')
  })
  it('合法 ISO 按目标时区格式化', () => {
    const out = formatTimeInZone('2026-07-16T00:00:00Z', 'Asia/Hong_Kong')
    expect(out).toContain('08:00')
  })
})

describe('categoryAnchorId', () => {
  it('生成稳定锚点 id', () => {
    expect(categoryAnchorId('us_markets')).toBe('cal-cat-us_markets')
  })
})

const SNAPSHOT = {
  status: 'success',
  data: {
    timezone: 'Asia/Hong_Kong',
    server_time: '2026-07-16T00:00:00Z',
    categories: [
      {
        category: 'us_markets',
        display_name: 'US Markets',
        is_market_open: true,
        next_session_change: null,
        tiles: [
          {
            symbol: 'SPX',
            display_name: 'S&P 500',
            yf_ticker: '^GSPC',
            price: 5000,
            change_abs: 10,
            change_pct: 0.2,
            sparkline: [1, 2, 3],
            updated_at: '2026-07-16',
            is_stale: false,
            source: 'YFinance',
            category: 'us_markets',
          },
        ],
      },
      {
        category: 'crypto',
        display_name: 'Crypto',
        is_market_open: true,
        next_session_change: null,
        tiles: [
          {
            symbol: 'BTC',
            display_name: '比特币',
            yf_ticker: 'BTC-USD',
            price: 60000,
            change_abs: -100,
            change_pct: -0.5,
            sparkline: [1, 2, 3],
            updated_at: '2026-07-16',
            is_stale: true,
            source: 'N/A',
            category: 'crypto',
          },
        ],
      },
    ],
  },
  updated_at: '2026-07-16T00:00:00Z',
}

describe('CalendarsModule', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(apiClient.get as any).mockImplementation(async (path: string) => {
      if (path === '/calendars/snapshot') return { data: SNAPSHOT }
      return { data: { status: 'success', data: { timezones: [], markets: [] } } }
    })
  })

  it('渲染标题与 6 个 Tab', async () => {
    const { CalendarsModule } = await import('../module')
    render(
      <MemoryRouter>
        <CalendarsModule />
      </MemoryRouter>,
    )
    expect(screen.getByText('全球市场日历')).toBeInTheDocument()
    for (const t of ['Markets', 'Economic', 'Earnings', 'Dividends', 'IPOs', 'Hours']) {
      expect(screen.getByText(t)).toBeInTheDocument()
    }
  })

  it('Markets Tab 按类目渲染横向卡片', async () => {
    const { CalendarsModule } = await import('../module')
    render(
      <MemoryRouter>
        <CalendarsModule />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText('S&P 500').length).toBeGreaterThan(0)
    })
    // 类目侧栏出现 US Markets
    expect(screen.getAllByText('US Markets').length).toBeGreaterThan(0)
  })

  it('STALE 卡片显示角标', async () => {
    const { CalendarsModule } = await import('../module')
    render(
      <MemoryRouter>
        <CalendarsModule />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText('STALE').length).toBeGreaterThan(0)
    })
  })

  it('切换到 Hours Tab 触发 /calendars/hours 请求', async () => {
    const { CalendarsModule } = await import('../module')
    render(
      <MemoryRouter>
        <CalendarsModule />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByText('Hours'))
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith('/calendars/hours')
    })
  })
})
