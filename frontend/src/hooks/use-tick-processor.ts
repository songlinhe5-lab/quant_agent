/**
 * 零 GC Tick 数据处理 Hook
 * FE-07: 高频 Tick 数据必须走 Float64Array + useRef，严禁触发 React state 重渲染
 * 
 * 设计原则:
 * 1. 使用 Float64Array 存储数值数据，避免对象数组的 GC 压力
 * 2. 使用 useRef 存储可变数据，不触发重渲染
 * 3. 通过 requestAnimationFrame 节流更新 UI
 * 4. 支持环形缓冲区，防止内存无限增长
 */

import { useRef, useCallback, useEffect, useState } from 'react'
import logger from '@/lib/logger'

// ─── Tick 数据结构 ──────────────────────────────────────────────────
// [timestamp, price, volume, bid, ask, bidSize, askSize]
const TICK_FIELDS = 7
const TIMESTAMP_IDX = 0
const PRICE_IDX = 1
const VOLUME_IDX = 2
const BID_IDX = 3
const ASK_IDX = 4
const BID_SIZE_IDX = 5
const ASK_SIZE_IDX = 6

// ─── 配置 ──────────────────────────────────────────────────────────
interface TickBufferConfig {
  capacity: number          // 缓冲区容量（tick 数量）
  flushInterval: number     // UI 刷新间隔 (ms)
  enableLogging: boolean    // 是否启用日志
}

const DEFAULT_CONFIG: TickBufferConfig = {
  capacity: 10000,          // 默认 10000 条 tick
  flushInterval: 100,       // 100ms 刷新一次 UI
  enableLogging: false,
}

// ─── 环形缓冲区 ────────────────────────────────────────────────────
export class TickRingBuffer {
  private buffer: Float64Array
  private capacity: number
  private head: number = 0    // 写入位置
  private count: number = 0   // 有效数据量

  constructor(capacity: number) {
    this.capacity = capacity
    // 预分配内存，避免运行时扩容
    this.buffer = new Float64Array(capacity * TICK_FIELDS)
  }

  /**
   * 写入一条 tick 数据
   */
  push(
    timestamp: number,
    price: number,
    volume: number,
    bid: number = 0,
    ask: number = 0,
    bidSize: number = 0,
    askSize: number = 0
  ): void {
    const offset = this.head * TICK_FIELDS
    this.buffer[offset + TIMESTAMP_IDX] = timestamp
    this.buffer[offset + PRICE_IDX] = price
    this.buffer[offset + VOLUME_IDX] = volume
    this.buffer[offset + BID_IDX] = bid
    this.buffer[offset + ASK_IDX] = ask
    this.buffer[offset + BID_SIZE_IDX] = bidSize
    this.buffer[offset + ASK_SIZE_IDX] = askSize

    this.head = (this.head + 1) % this.capacity
    if (this.count < this.capacity) this.count++
  }

  /**
   * 获取最新价格
   */
  getLatestPrice(): number {
    if (this.count === 0) return 0
    const idx = ((this.head - 1 + this.capacity) % this.capacity) * TICK_FIELDS + PRICE_IDX
    return this.buffer[idx]
  }

  /**
   * 获取最新 tick
   */
  getLatest(): TickData | null {
    if (this.count === 0) return null
    const offset = ((this.head - 1 + this.capacity) % this.capacity) * TICK_FIELDS
    return {
      timestamp: this.buffer[offset + TIMESTAMP_IDX],
      price: this.buffer[offset + PRICE_IDX],
      volume: this.buffer[offset + VOLUME_IDX],
      bid: this.buffer[offset + BID_IDX],
      ask: this.buffer[offset + ASK_IDX],
      bidSize: this.buffer[offset + BID_SIZE_IDX],
      askSize: this.buffer[offset + ASK_SIZE_IDX],
    }
  }

  /**
   * 获取最近 N 条数据（用于图表）
   */
  getRecent(n: number): TickData[] {
    const count = Math.min(n, this.count)
    const result: TickData[] = []
    
    for (let i = 0; i < count; i++) {
      const idx = ((this.head - 1 - i + this.capacity) % this.capacity) * TICK_FIELDS
      result.unshift({
        timestamp: this.buffer[idx + TIMESTAMP_IDX],
        price: this.buffer[idx + PRICE_IDX],
        volume: this.buffer[idx + VOLUME_IDX],
        bid: this.buffer[idx + BID_IDX],
        ask: this.buffer[idx + ASK_IDX],
        bidSize: this.buffer[idx + BID_SIZE_IDX],
        askSize: this.buffer[idx + ASK_SIZE_IDX],
      })
    }
    
    return result
  }

  /**
   * 获取价格序列（用于计算指标）
   */
  getPriceArray(length: number): Float64Array {
    const count = Math.min(length, this.count)
    const prices = new Float64Array(count)
    
    for (let i = 0; i < count; i++) {
      const idx = ((this.head - 1 - i + this.capacity) % this.capacity) * TICK_FIELDS + PRICE_IDX
      prices[count - 1 - i] = this.buffer[idx]
    }
    
    return prices
  }

  /**
   * 清空缓冲区
   */
  clear(): void {
    this.head = 0
    this.count = 0
  }

  /**
   * 获取统计信息
   */
  getStats(): { count: number; capacity: number; utilization: number } {
    return {
      count: this.count,
      capacity: this.capacity,
      utilization: this.count / this.capacity,
    }
  }
}

// ─── Tick 数据结构 ──────────────────────────────────────────────────
export interface TickData {
  timestamp: number
  price: number
  volume: number
  bid: number
  ask: number
  bidSize: number
  askSize: number
}

// ─── 显示状态（节流更新） ──────────────────────────────────────────
export interface TickDisplayState {
  price: number
  change: number
  changePercent: number
  volume: number
  bid: number
  ask: number
  spread: number
  timestamp: number
}

// ─── Hook: 零 GC Tick 处理 ─────────────────────────────────────────
export function useTickProcessor(symbol: string, config: Partial<TickBufferConfig> = {}) {
  const mergedConfig = { ...DEFAULT_CONFIG, ...config }
  
  // 使用 ref 存储缓冲区，不触发重渲染
  const bufferRef = useRef<TickRingBuffer | null>(null)
  const prevPriceRef = useRef<number>(0)
  const rafRef = useRef<number | null>(null)
  const lastFlushRef = useRef<number>(0)

  // 只有显示用的 state（节流更新）
  const [display, setDisplay] = useState<TickDisplayState>({
    price: 0,
    change: 0,
    changePercent: 0,
    volume: 0,
    bid: 0,
    ask: 0,
    spread: 0,
    timestamp: 0,
  })

  // 初始化缓冲区
  if (!bufferRef.current) {
    bufferRef.current = new TickRingBuffer(mergedConfig.capacity)
  }

  // ─── 处理新 Tick ────────────────────────────────────────────────
  const onTick = useCallback((tick: Omit<TickData, 'timestamp'> & { timestamp?: number }) => {
    const buffer = bufferRef.current
    if (!buffer) return

    const timestamp = tick.timestamp ?? Date.now()
    buffer.push(
      timestamp,
      tick.price,
      tick.volume,
      tick.bid ?? 0,
      tick.ask ?? 0,
      tick.bidSize ?? 0,
      tick.askSize ?? 0
    )

    // 节流更新 UI
    const now = performance.now()
    if (now - lastFlushRef.current >= mergedConfig.flushInterval) {
      lastFlushRef.current = now
      
      // 使用 rAF 确保在下一帧更新
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      rafRef.current = requestAnimationFrame(() => {
        const latest = buffer.getLatest()
        if (!latest) return

        const prevPrice = prevPriceRef.current
        const change = prevPrice > 0 ? latest.price - prevPrice : 0
        const changePercent = prevPrice > 0 ? (change / prevPrice) * 100 : 0

        setDisplay({
          price: latest.price,
          change,
          changePercent,
          volume: latest.volume,
          bid: latest.bid,
          ask: latest.ask,
          spread: latest.ask - latest.bid,
          timestamp: latest.timestamp,
        })

        prevPriceRef.current = latest.price
      })
    }
  }, [mergedConfig.flushInterval])

  // ─── 获取缓冲区引用 ─────────────────────────────────────────────
  const getBuffer = useCallback((): TickRingBuffer | null => {
    return bufferRef.current
  }, [])

  // ─── 获取最近数据 ───────────────────────────────────────────────
  const getRecentTicks = useCallback((n: number = 100): TickData[] => {
    return bufferRef.current?.getRecent(n) ?? []
  }, [])

  // ─── 清理 ───────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  // ─── 切换标的时重置 ─────────────────────────────────────────────
  useEffect(() => {
    bufferRef.current?.clear()
    prevPriceRef.current = 0
    setDisplay({
      price: 0,
      change: 0,
      changePercent: 0,
      volume: 0,
      bid: 0,
      ask: 0,
      spread: 0,
      timestamp: 0,
    })
  }, [symbol])

  return {
    display,
    onTick,
    getBuffer,
    getRecentTicks,
    stats: bufferRef.current?.getStats() ?? { count: 0, capacity: 0, utilization: 0 },
  }
}

// ─── 工具函数：批量写入 ─────────────────────────────────────────────
export function batchWriteTicks(
  buffer: TickRingBuffer,
  ticks: Array<{ price: number; volume: number; timestamp?: number }>
): void {
  const now = Date.now()
  for (const tick of ticks) {
    buffer.push(tick.timestamp ?? now, tick.price, tick.volume)
  }
}

export default useTickProcessor
