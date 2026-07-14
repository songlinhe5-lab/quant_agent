/**
 * FE-11 / FE-13 / FE-28: DataState · VirtualList · motion
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DataState, resolveDataStatus } from '@/components/data-state'
import { MOTION } from '@/lib/motion'
import { VirtualList } from '@/components/virtual-list'

describe('resolveDataStatus (FE-11)', () => {
  it('prioritizes loading > empty > stale > ready', () => {
    expect(resolveDataStatus({ loading: true, empty: true, stale: true })).toBe('loading')
    expect(resolveDataStatus({ empty: true, stale: true })).toBe('empty')
    expect(resolveDataStatus({ stale: true })).toBe('stale')
    expect(resolveDataStatus({})).toBe('ready')
  })
})

describe('DataState (FE-11)', () => {
  it('renders skeleton when loading', () => {
    render(
      <DataState status="loading" skeletonRows={3}>
        <div>content</div>
      </DataState>,
    )
    expect(screen.getByTestId('data-state-loading')).toBeTruthy()
    expect(screen.queryByText('content')).toBeNull()
  })

  it('renders empty state', () => {
    render(
      <DataState status="empty" emptyTitle="空空如也">
        <div>content</div>
      </DataState>,
    )
    expect(screen.getByTestId('data-state-empty')).toBeTruthy()
    expect(screen.getByText('空空如也')).toBeTruthy()
  })

  it('shows STALE badge when stale', () => {
    render(
      <DataState status="stale">
        <div>live</div>
      </DataState>,
    )
    expect(screen.getByTestId('data-state-ready')).toBeTruthy()
    expect(screen.getByText('STALE')).toBeTruthy()
    expect(screen.getByText('live')).toBeTruthy()
  })
})

describe('MOTION (FE-28)', () => {
  it('matches product toast / transition timings', () => {
    expect(MOTION.fast).toBe(150)
    expect(MOTION.base).toBe(200)
    expect(MOTION.slow).toBe(300)
    expect(MOTION.toast).toBe(4500)
  })
})

describe('VirtualList (FE-13)', () => {
  it('renders only a window of items', () => {
    const items = Array.from({ length: 200 }, (_, i) => ({ id: `r${i}`, label: `Row ${i}` }))
    render(
      <VirtualList
        items={items}
        estimateSize={40}
        height={200}
        getKey={(item) => item.id}
        renderItem={(item) => <div>{item.label}</div>}
      />,
    )
    expect(screen.getByTestId('virtual-list')).toBeTruthy()
    expect(screen.getByText('Row 0')).toBeTruthy()
    expect(screen.queryByText('Row 199')).toBeNull()
  })
})
