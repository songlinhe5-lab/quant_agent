/**
 * IndexedDB K线本地缓存
 * FE-19: 减少重复 HTTP 拉取，离线可读最近行情
 */

import type { Kline, KlinePeriod } from '@/types/domain'
import logger from '@/lib/logger'

// ─── 配置 ──────────────────────────────────────────────────────────
const DB_NAME = 'quant_agent_klines'
const DB_VERSION = 1
const STORE_NAME = 'klines'
const MAX_AGE_DAYS = 30  // 最多保留 30 天数据

// ─── 缓存键结构 ────────────────────────────────────────────────────
interface KlineCacheKey {
  symbol: string
  period: KlinePeriod
}

interface KlineCacheEntry {
  symbol: string
  period: KlinePeriod
  klines: Kline[]
  updatedAt: number
  expiresAt: number
}

// ─── IndexedDB 封装 ────────────────────────────────────────────────
class KlineCache {
  private db: IDBDatabase | null = null
  private initPromise: Promise<void> | null = null

  /**
   * 初始化数据库
   */
  async init(): Promise<void> {
    if (this.db) return
    if (this.initPromise) return this.initPromise

    this.initPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onerror = () => {
        logger.error('[KlineCache] IndexedDB 打开失败', request.error as unknown as Error)
        reject(request.error)
      }

      request.onsuccess = () => {
        this.db = request.result
        logger.debug('[KlineCache] IndexedDB 初始化成功')
        resolve()
      }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' })
          store.createIndex('symbol', 'symbol', { unique: false })
          store.createIndex('expiresAt', 'expiresAt', { unique: false })
        }
      }
    })

    return this.initPromise
  }

  /**
   * 生成缓存键
   */
  private getKey(symbol: string, period: KlinePeriod): string {
    return `${symbol}:${period}`
  }

  /**
   * 存储 K线数据
   */
  async set(symbol: string, period: KlinePeriod, klines: Kline[]): Promise<void> {
    await this.init()
    if (!this.db) return

    const now = Date.now()
    const entry: KlineCacheEntry & { id: string } = {
      id: this.getKey(symbol, period),
      symbol,
      period,
      klines,
      updatedAt: now,
      expiresAt: now + MAX_AGE_DAYS * 24 * 60 * 60 * 1000,
    }

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const request = store.put(entry)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 读取 K线数据
   */
  async get(symbol: string, period: KlinePeriod): Promise<Kline[] | null> {
    await this.init()
    if (!this.db) return null

    const key = this.getKey(symbol, period)

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const request = store.get(key)

      request.onsuccess = () => {
        const entry = request.result as (KlineCacheEntry & { id: string }) | undefined
        
        if (!entry) {
          resolve(null)
          return
        }

        // 检查是否过期
        if (entry.expiresAt < Date.now()) {
          // 过期，删除
          this.delete(symbol, period)
          resolve(null)
          return
        }

        resolve(entry.klines)
      }

      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 删除缓存
   */
  async delete(symbol: string, period: KlinePeriod): Promise<void> {
    await this.init()
    if (!this.db) return

    const key = this.getKey(symbol, period)

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const request = store.delete(key)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 清理过期数据
   */
  async cleanup(): Promise<number> {
    await this.init()
    if (!this.db) return 0

    const now = Date.now()
    let deletedCount = 0

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const index = store.index('expiresAt')
      const range = IDBKeyRange.upperBound(now)

      const request = index.openCursor(range)

      request.onsuccess = () => {
        const cursor = request.result
        if (cursor) {
          cursor.delete()
          deletedCount++
          cursor.continue()
        } else {
          logger.info(`[KlineCache] 清理完成，删除 ${deletedCount} 条过期数据`)
          resolve(deletedCount)
        }
      }

      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 获取所有缓存的标的
   */
  async getCachedSymbols(): Promise<string[]> {
    await this.init()
    if (!this.db) return []

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const index = store.index('symbol')
      const request = index.openKeyCursor()
      const symbols = new Set<string>()

      request.onsuccess = () => {
        const cursor = request.result
        if (cursor) {
          const key = cursor.key as string
          const symbol = key.split(':')[0]
          symbols.add(symbol)
          cursor.continue()
        } else {
          resolve(Array.from(symbols))
        }
      }

      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 获取缓存统计
   */
  async stats(): Promise<{ count: number; symbols: string[] }> {
    await this.init()
    if (!this.db) return { count: 0, symbols: [] }

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const countRequest = store.count()
      const symbols: string[] = []

      countRequest.onsuccess = () => {
        const count = countRequest.result

        // 获取所有 symbol
        const cursorRequest = store.openCursor()
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result
          if (cursor) {
            const entry = cursor.value as KlineCacheEntry
            if (!symbols.includes(entry.symbol)) {
              symbols.push(entry.symbol)
            }
            cursor.continue()
          } else {
            resolve({ count, symbols })
          }
        }
        cursorRequest.onerror = () => reject(cursorRequest.error)
      }

      countRequest.onerror = () => reject(countRequest.error)
    })
  }

  /**
   * 清空所有缓存
   */
  async clear(): Promise<void> {
    await this.init()
    if (!this.db) return

    return new Promise((resolve, reject) => {
      const tx = this.db!.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const request = store.clear()

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }
}

// ─── 导出单例 ──────────────────────────────────────────────────────
export const klineCache = new KlineCache()

// 启动时自动清理过期数据
if (typeof window !== 'undefined') {
  setTimeout(() => {
    klineCache.cleanup().catch(() => {})
  }, 5000)
}

// ─── React Hook ────────────────────────────────────────────────────
import { useState, useEffect, useCallback } from 'react'

/**
 * K线缓存 Hook
 */
export function useKlineCache(symbol: string, period: KlinePeriod) {
  const [klines, setKlines] = useState<Kline[] | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isFromCache, setIsFromCache] = useState(false)

  // 从缓存加载
  useEffect(() => {
    let cancelled = false

    async function loadFromCache() {
      setIsLoading(true)
      try {
        const cached = await klineCache.get(symbol, period)
        if (!cancelled) {
          setKlines(cached)
          setIsFromCache(cached !== null)
        }
      } catch (e) {
        logger.warn('[useKlineCache] 读取缓存失败', { error: (e as Error).message })
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadFromCache()
    return () => { cancelled = true }
  }, [symbol, period])

  // 更新缓存
  const updateCache = useCallback(async (newKlines: Kline[]) => {
    setKlines(newKlines)
    setIsFromCache(false)
    try {
      await klineCache.set(symbol, period, newKlines)
    } catch (e) {
      logger.warn('[useKlineCache] 写入缓存失败', { error: (e as Error).message })
    }
  }, [symbol, period])

  return { klines, isLoading, isFromCache, updateCache }
}

export default klineCache
