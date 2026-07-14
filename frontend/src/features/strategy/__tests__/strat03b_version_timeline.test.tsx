/**
 * STRAT-03b: 版本时间线组件测试
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { VersionTimeline } from '../layout/version-timeline'
import { useStrategyStore } from '../stores'

// Mock apiClient
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

// Mock useToast
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: vi.fn(),
  }),
}))

describe('STRAT-03b: VersionTimeline', () => {
  beforeEach(() => {
    // Reset store
    useStrategyStore.setState({
      activeStrategy: '',
      enterDiff: vi.fn(),
    })
  })

  it('should show placeholder when no strategy selected', () => {
    render(<VersionTimeline />)
    expect(screen.getByText('请先选择一个策略')).toBeInTheDocument()
  })

  it('should show loading state', async () => {
    useStrategyStore.setState({ activeStrategy: 'TestStrategy' })
    
    // Mock delayed API response
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ data: { status: 'success', data: [] } }), 100))
    )
    
    render(<VersionTimeline />)
    
    // Should show loading initially
    await waitFor(() => {
      expect(screen.getByText('暂无版本记录')).toBeInTheDocument()
    })
  })

  it('should show empty state when no versions', async () => {
    useStrategyStore.setState({ activeStrategy: 'TestStrategy' })
    
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { status: 'success', data: [] } })
    
    render(<VersionTimeline />)
    
    await waitFor(() => {
      expect(screen.getByText('暂无版本记录')).toBeInTheDocument()
      expect(screen.getByText('保存策略后将自动创建版本')).toBeInTheDocument()
    })
  })

  it('should render version list', async () => {
    useStrategyStore.setState({ activeStrategy: 'TestStrategy' })
    
    const mockVersions = [
      {
        id: 'v1',
        seq: 1,
        source: 'manual',
        message: 'Initial version',
        code_hash: 'abc12345',
        parent_id: null,
        created_at: '2025-01-13T10:00:00Z',
      },
      {
        id: 'v2',
        seq: 2,
        source: 'ai-apply',
        message: 'AI generated',
        code_hash: 'def67890',
        parent_id: null,
        created_at: '2025-01-13T11:00:00Z',
      },
    ]
    
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { status: 'success', data: mockVersions } })
    
    render(<VersionTimeline />)
    
    await waitFor(() => {
      expect(screen.getByText('v1')).toBeInTheDocument()
      expect(screen.getByText('v2')).toBeInTheDocument()
      expect(screen.getByText('Initial version')).toBeInTheDocument()
      expect(screen.getByText('AI generated')).toBeInTheDocument()
    })
  })

  it('should show source badges', async () => {
    useStrategyStore.setState({ activeStrategy: 'TestStrategy' })
    
    const mockVersions = [
      {
        id: 'v1',
        seq: 1,
        source: 'manual',
        message: null,
        code_hash: 'abc12345',
        parent_id: null,
        created_at: null,
      },
    ]
    
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { status: 'success', data: mockVersions } })
    
    render(<VersionTimeline />)
    
    await waitFor(() => {
      expect(screen.getByText('手动')).toBeInTheDocument()
    })
  })

  it('should show restore indicator for restored versions', async () => {
    useStrategyStore.setState({ activeStrategy: 'TestStrategy' })
    
    const mockVersions = [
      {
        id: 'v2',
        seq: 2,
        source: 'restore',
        message: '恢复自版本 v1',
        code_hash: 'abc12345',
        parent_id: 'v1-uuid',
        created_at: null,
      },
    ]
    
    const { apiClient } = await import('@/lib/api-client')
    vi.mocked(apiClient.get).mockResolvedValue({ data: { status: 'success', data: mockVersions } })
    
    render(<VersionTimeline />)
    
    await waitFor(() => {
      expect(screen.getByText(/← 恢复自/)).toBeInTheDocument()
    })
  })
})
