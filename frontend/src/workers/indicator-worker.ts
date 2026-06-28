/**
 * Web Worker 技术指标计算
 * FE-20: MACD / RSI / 布林带等重度计算移出主线程，防止阻塞渲染
 */

// ─── Worker 消息类型 ───────────────────────────────────────────────
export interface WorkerRequest {
  id: string
  type: 'calculate' | 'batch'
  indicator: IndicatorType
  data: number[]
  params?: Record<string, number>
}

export interface WorkerResponse {
  id: string
  type: 'result' | 'error'
  indicator: IndicatorType
  result?: IndicatorResult
  error?: string
}

export type IndicatorType = 'MA' | 'EMA' | 'MACD' | 'RSI' | 'KDJ' | 'BOLL' | 'ATR'

export interface IndicatorResult {
  values: Record<string, number>[]
  signal?: string
}

// ─── Worker 代码（内联）────────────────────────────────────────────
const workerCode = `
'use strict'

// MA 移动平均
function calculateMA(data, params) {
  const period = params.period || 20
  const result = []
  
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push({ ma: null })
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j]
      }
      result.push({ ma: sum / period })
    }
  }
  
  return { values: result }
}

// EMA 指数移动平均
function calculateEMA(data, params) {
  const period = params.period || 20
  const multiplier = 2 / (period + 1)
  const result = [{ ema: data[0] }]
  
  for (let i = 1; i < data.length; i++) {
    const ema = (data[i] - result[i - 1].ema) * multiplier + result[i - 1].ema
    result.push({ ema })
  }
  
  return { values: result }
}

// MACD
function calculateMACD(data, params) {
  const fastPeriod = params.fastPeriod || 12
  const slowPeriod = params.slowPeriod || 26
  const signalPeriod = params.signalPeriod || 9
  
  const fastMultiplier = 2 / (fastPeriod + 1)
  const slowMultiplier = 2 / (slowPeriod + 1)
  const signalMultiplier = 2 / (signalPeriod + 1)
  
  let fastEMA = data[0]
  let slowEMA = data[0]
  const result = []
  
  for (let i = 0; i < data.length; i++) {
    if (i === 0) {
      result.push({ macd: 0, signal: 0, histogram: 0 })
      continue
    }
    
    fastEMA = (data[i] - fastEMA) * fastMultiplier + fastEMA
    slowEMA = (data[i] - slowEMA) * slowMultiplier + slowEMA
    
    const macd = fastEMA - slowEMA
    const prevSignal = result[i - 1].signal
    const signal = (macd - prevSignal) * signalMultiplier + prevSignal
    const histogram = macd - signal
    
    result.push({ macd, signal, histogram })
  }
  
  // 生成信号
  const last = result[result.length - 1]
  const prev = result[result.length - 2]
  let signal = 'neutral'
  if (prev && last.histogram > 0 && prev.histogram <= 0) signal = 'buy'
  if (prev && last.histogram < 0 && prev.histogram >= 0) signal = 'sell'
  
  return { values: result, signal }
}

// RSI 相对强弱指标
function calculateRSI(data, params) {
  const period = params.period || 14
  const result = [{ rsi: null }]
  
  let gains = 0
  let losses = 0
  
  for (let i = 1; i < data.length; i++) {
    const change = data[i] - data[i - 1]
    
    if (i <= period) {
      if (change > 0) gains += change
      else losses -= change
      
      if (i === period) {
        const avgGain = gains / period
        const avgLoss = losses / period
        const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
        result.push({ rsi: 100 - (100 / (1 + rs)) })
      } else {
        result.push({ rsi: null })
      }
    } else {
      const prevAvgGain = (result[i - 1].rsi !== null) 
        ? (100 / (100 - result[i - 1].rsi) - 1) * (losses / period) 
        : gains / period
      const prevAvgLoss = losses / period
      
      if (change > 0) {
        gains = (prevAvgGain * (period - 1) + change) / period
        losses = (prevAvgLoss * (period - 1)) / period
      } else {
        gains = (prevAvgGain * (period - 1)) / period
        losses = (prevAvgLoss * (period - 1) - change) / period
      }
      
      const rs = losses === 0 ? 100 : gains / losses
      result.push({ rsi: 100 - (100 / (1 + rs)) })
    }
  }
  
  // 生成信号
  const last = result[result.length - 1]
  let signal = 'neutral'
  if (last.rsi !== null) {
    if (last.rsi > 70) signal = 'overbought'
    else if (last.rsi < 30) signal = 'oversold'
  }
  
  return { values: result, signal }
}

// 布林带
function calculateBOLL(data, params) {
  const period = params.period || 20
  const multiplier = params.multiplier || 2
  const result = []
  
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push({ middle: null, upper: null, lower: null })
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j]
      }
      const ma = sum / period
      
      let variance = 0
      for (let j = 0; j < period; j++) {
        variance += Math.pow(data[i - j] - ma, 2)
      }
      const std = Math.sqrt(variance / period)
      
      result.push({
        middle: ma,
        upper: ma + multiplier * std,
        lower: ma - multiplier * std,
      })
    }
  }
  
  return { values: result }
}

// KDJ
function calculateKDJ(highs, lows, closes, params) {
  const period = params.period || 9
  const kSmooth = params.kSmooth || 3
  const dSmooth = params.dSmooth || 3
  const result = []
  
  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) {
      result.push({ k: null, d: null, j: null })
    } else {
      let highest = -Infinity
      let lowest = Infinity
      
      for (let j = 0; j < period; j++) {
        if (highs[i - j] > highest) highest = highs[i - j]
        if (lows[i - j] < lowest) lowest = lows[i - j]
      }
      
      const rsv = highest === lowest ? 50 : ((closes[i] - lowest) / (highest - lowest)) * 100
      
      const prevK = result[i - 1]?.k ?? 50
      const prevD = result[i - 1]?.d ?? 50
      
      const k = (2 / kSmooth) * prevK + (1 / kSmooth) * rsv
      const d = (2 / dSmooth) * prevD + (1 / dSmooth) * k
      const j = 3 * k - 2 * d
      
      result.push({ k, d, j })
    }
  }
  
  return { values: result }
}

// 消息处理
self.onmessage = function(e) {
  const { id, type, indicator, data, params } = e.data
  
  try {
    let result
    
    switch (indicator) {
      case 'MA':
        result = calculateMA(data, params || {})
        break
      case 'EMA':
        result = calculateEMA(data, params || {})
        break
      case 'MACD':
        result = calculateMACD(data, params || {})
        break
      case 'RSI':
        result = calculateRSI(data, params || {})
        break
      case 'BOLL':
        result = calculateBOLL(data, params || {})
        break
      default:
        throw new Error('Unknown indicator: ' + indicator)
    }
    
    self.postMessage({ id, type: 'result', indicator, result })
  } catch (error) {
    self.postMessage({ id, type: 'error', indicator, error: error.message })
  }
}
`

// ─── Worker 管理器 ─────────────────────────────────────────────────
class IndicatorWorker {
  private worker: Worker | null = null
  private pendingRequests: Map<string, {
    resolve: (result: IndicatorResult) => void
    reject: (error: Error) => void
  }> = new Map()
  private requestId = 0

  constructor() {
    this.initWorker()
  }

  private initWorker(): void {
    if (typeof Worker === 'undefined') {
      logger.warn('[IndicatorWorker] Web Worker 不可用，将使用主线程计算')
      return
    }

    try {
      const blob = new Blob([workerCode], { type: 'application/javascript' })
      const url = URL.createObjectURL(blob)
      this.worker = new Worker(url)
      URL.revokeObjectURL(url)

      this.worker.onmessage = (e: MessageEvent<WorkerResponse>) => {
        const { id, type, result, error } = e.data
        const pending = this.pendingRequests.get(id)
        
        if (!pending) return

        if (type === 'result' && result) {
          pending.resolve(result)
        } else {
          pending.reject(new Error(error || 'Worker 计算失败'))
        }
        
        this.pendingRequests.delete(id)
      }

      this.worker.onerror = (error) => {
        logger.error('[IndicatorWorker] Worker 错误', error as unknown as Error)
      }

      logger.debug('[IndicatorWorker] Worker 初始化成功')
    } catch (e) {
      logger.warn('[IndicatorWorker] Worker 创建失败', { error: (e as Error).message })
    }
  }

  /**
   * 计算指标
   */
  async calculate(
    indicator: IndicatorType,
    data: number[],
    params?: Record<string, number>
  ): Promise<IndicatorResult> {
    if (!this.worker) {
      // 降级到主线程计算
      return this.calculateMainThread(indicator, data, params)
    }

    const id = String(++this.requestId)

    return new Promise((resolve, reject) => {
      this.pendingRequests.set(id, { resolve, reject })
      
      this.worker!.postMessage({
        id,
        type: 'calculate',
        indicator,
        data,
        params,
      } as WorkerRequest)

      // 超时处理
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id)
          reject(new Error('Worker 计算超时'))
        }
      }, 10000)
    })
  }

  /**
   * 主线程降级计算
   */
  private async calculateMainThread(
    indicator: IndicatorType,
    data: number[],
    params?: Record<string, number>
  ): Promise<IndicatorResult> {
    // 简单的同步计算实现
    const p = params || {}
    
    switch (indicator) {
      case 'MA': {
        const period = p.period || 20
        const values = []
        for (let i = 0; i < data.length; i++) {
          if (i < period - 1) {
            values.push({ ma: null as number | null })
          } else {
            let sum = 0
            for (let j = 0; j < period; j++) sum += data[i - j]
            values.push({ ma: sum / period })
          }
        }
        return { values }
      }
      default:
        throw new Error(`主线程降级不支持 ${indicator} 计算`)
    }
  }

  /**
   * 销毁 Worker
   */
  destroy(): void {
    if (this.worker) {
      this.worker.terminate()
      this.worker = null
    }
    this.pendingRequests.clear()
  }
}

// ─── 导出单例 ──────────────────────────────────────────────────────
export const indicatorWorker = new IndicatorWorker()

// ─── React Hook ────────────────────────────────────────────────────
import { useState, useEffect } from 'react'

/**
 * 技术指标计算 Hook
 */
export function useIndicator(
  indicator: IndicatorType,
  data: number[],
  params?: Record<string, number>
) {
  const [result, setResult] = useState<IndicatorResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!data || data.length === 0) return

    let cancelled = false
    setIsLoading(true)
    setError(null)

    indicatorWorker
      .calculate(indicator, data, params)
      .then((res) => {
        if (!cancelled) {
          setResult(res)
          setIsLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err)
          setIsLoading(false)
        }
      })

    return () => { cancelled = true }
  }, [indicator, data.length, JSON.stringify(params)])

  return { result, isLoading, error }
}

export default indicatorWorker
