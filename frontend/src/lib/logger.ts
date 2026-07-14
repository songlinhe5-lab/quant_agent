/**
 * 前端日志系统
 * FE-05: level 过滤 + 生产环境上报 /api/v1/logs/frontend
 */

import { API_BASE_URL } from './constants'

// 日志级别
export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
}

// 日志条目结构
export interface LogEntry {
  timestamp: string
  level: LogLevel
  message: string
  context?: Record<string, unknown>
  error?: {
    name: string
    message: string
    stack?: string
  }
}

// 配置
interface LoggerConfig {
  minLevel: LogLevel
  enableConsole: boolean
  enableRemote: boolean
  remoteEndpoint: string
  batchSize: number
  flushInterval: number
}

const DEFAULT_CONFIG: LoggerConfig = {
  minLevel: LogLevel.DEBUG,
  enableConsole: true,
  enableRemote: import.meta.env.PROD,
  remoteEndpoint: `${API_BASE_URL}/logs/frontend`,
  batchSize: 20,
  flushInterval: 5000,
}

class Logger {
  private config: LoggerConfig
  private buffer: LogEntry[] = []
  private flushTimer: ReturnType<typeof setInterval> | null = null

  constructor(config: Partial<LoggerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    
    // 生产环境启动定时刷新
    if (this.config.enableRemote) {
      this.flushTimer = setInterval(() => this.flush(), this.config.flushInterval)
    }
  }

  /**
   * 设置日志级别
   */
  setLevel(level: LogLevel): void {
    this.config.minLevel = level
  }

  /**
   * Debug 日志
   */
  debug(message: string, context?: Record<string, unknown>): void {
    this.log(LogLevel.DEBUG, message, context)
  }

  /**
   * Info 日志
   */
  info(message: string, context?: Record<string, unknown>): void {
    this.log(LogLevel.INFO, message, context)
  }

  /**
   * Warn 日志
   */
  warn(message: string, context?: Record<string, unknown>): void {
    this.log(LogLevel.WARN, message, context)
  }

  /**
   * Error 日志
   */
  error(message: string, error?: Error, context?: Record<string, unknown>): void {
    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level: LogLevel.ERROR,
      message,
      context,
      error: error ? {
        name: error.name,
        message: error.message,
        stack: error.stack,
      } : undefined,
    }

    this.processEntry(entry)
  }

  /**
   * 核心日志处理
   */
  private log(level: LogLevel, message: string, context?: Record<string, unknown>): void {
    if (level < this.config.minLevel) return

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      context,
    }

    this.processEntry(entry)
  }

  private processEntry(entry: LogEntry): void {
    // 控制台输出
    if (this.config.enableConsole) {
      this.outputToConsole(entry)
    }

    // 加入缓冲区
    if (this.config.enableRemote) {
      this.buffer.push(entry)
      if (this.buffer.length >= this.config.batchSize) {
        this.flush()
      }
    }
  }

  /**
   * 控制台输出
   */
  private outputToConsole(entry: LogEntry): void {
    const prefix = `[${entry.timestamp}] ${LogLevel[entry.level]}`
    const contextStr = entry.context ? ` ${JSON.stringify(entry.context)}` : ''

    switch (entry.level) {
      case LogLevel.DEBUG:
        console.debug(`${prefix}: ${entry.message}${contextStr}`)
        break
      case LogLevel.INFO:
        console.info(`${prefix}: ${entry.message}${contextStr}`)
        break
      case LogLevel.WARN:
        console.warn(`${prefix}: ${entry.message}${contextStr}`)
        break
      case LogLevel.ERROR:
        console.error(`${prefix}: ${entry.message}${contextStr}`, entry.error)
        break
    }
  }

  /**
   * 刷新缓冲区，上报到后端
   */
  async flush(): Promise<void> {
    if (this.buffer.length === 0) return

    const entries = [...this.buffer]
    this.buffer = []

    try {
      // 日志上报使用 withCredentials 自动携带 HttpOnly Cookie
      await fetch(this.config.remoteEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ logs: entries }),
        keepalive: true,
      })
    } catch (e) {
      // 上报失败，将日志放回缓冲区（限制大小防止内存泄漏）
      if (this.buffer.length < 1000) {
        this.buffer.unshift(...entries)
      }
      console.warn('[Logger] 远程日志上报失败', e)
    }
  }

  /**
   * 清理定时器
   */
  destroy(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer)
      this.flushTimer = null
    }
    this.flush()
  }
}

// 全局单例
export const logger = new Logger({
  minLevel: import.meta.env.DEV ? LogLevel.DEBUG : LogLevel.INFO,
})

// 页面卸载前刷新日志
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    logger.flush()
  })
}

export default logger
