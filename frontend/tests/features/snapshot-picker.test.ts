/**
 * FE-PROD-04: 快照选择 / 可复现性徽章
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { extractReproducibilityBadge } from '@/features/backtest/reproducibility-badge'
import { LATEST_PUBLISHED } from '@/types/datalake'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

import { apiClient } from '@/lib/api-client'
import { useDatalakeSnapshots } from '@/hooks/use-datalake-snapshots'

const mockGet = vi.mocked(apiClient.get)

describe('extractReproducibilityBadge', () => {
  it('reads badge field', () => {
    const b = extractReproducibilityBadge({
      badge: {
        code_hash: 'abcdef123456',
        manifest_hash: 'ffffeeee',
        reproducible: true,
        data_snapshot_id: 'snap_20260713',
      },
    })
    expect(b?.reproducible).toBe(true)
    expect(b?.code_hash).toBe('abcdef123456')
    expect(b?.data_snapshot_id).toBe('snap_20260713')
  })

  it('falls back to manifest summary', () => {
    const b = extractReproducibilityBadge({
      manifest: {
        code_hash: 'aa'.repeat(32),
        manifest_hash: null,
        reproducible: false,
        data_snapshot_id: LATEST_PUBLISHED,
        data_mode: 'unbound',
      },
    })
    expect(b?.reproducible).toBe(false)
    expect(b?.manifest_hash).toBeNull()
  })

  it('returns null without fingerprints', () => {
    expect(extractReproducibilityBadge({ metrics: {} })).toBeNull()
    expect(extractReproducibilityBadge(null)).toBeNull()
  })
})

describe('useDatalakeSnapshots', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads published list and latest', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url.includes('/latest')) {
        return {
          data: {
            status: 'success',
            data: {
              snapshot_id: 'snap_20260713',
              as_of_date: '2026-07-13',
              status: 'published',
              manifest_hash: 'abc',
              stale_warning: false,
            },
          },
        } as never
      }
      return {
        data: {
          status: 'success',
          data: [
            {
              snapshot_id: 'snap_20260713',
              as_of_date: '2026-07-13',
              status: 'published',
              manifest_hash: 'abc',
              ticker_count: 10,
              total_bytes: 1,
              is_monthly_anchor: false,
              storage_tier: 'hot',
              published_at: null,
            },
          ],
        },
      } as never
    })

    const { result } = renderHook(() => useDatalakeSnapshots(true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.snapshots).toHaveLength(1)
    expect(result.current.latest?.snapshot_id).toBe('snap_20260713')
    expect(result.current.error).toBeNull()
  })
})
