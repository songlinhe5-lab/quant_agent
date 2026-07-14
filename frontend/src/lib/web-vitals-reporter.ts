/**
 * OBS-03 / FE-27: Web Vitals 采集与上报
 *
 * - Dev: console + 右下角轻量 HUD
 * - Prod: 聚合后 POST /api/v1/client/heartbeat（platform=web）
 */

import { onCLS, onINP, onLCP, onTTFB, type Metric } from 'web-vitals'
import { API_BASE_URL } from '@/lib/api-client'
import { logger } from '@/lib/logger'

const DEVICE_KEY = 'qa_web_device_id'
const APP_VERSION = import.meta.env.VITE_APP_VERSION || '0.1.0'

export type WebVitalSnapshot = {
  lcpMs?: number
  cls?: number
  inpMs?: number
  ttfbMs?: number
}

const snapshot: WebVitalSnapshot = {}
let reportTimer: ReturnType<typeof setTimeout> | null = null
let hudEl: HTMLDivElement | null = null

function getDeviceId(): string {
  try {
    let id = sessionStorage.getItem(DEVICE_KEY)
    if (!id) {
      id = crypto.randomUUID()
      sessionStorage.setItem(DEVICE_KEY, id)
    }
    return id
  } catch {
    return `web-${Date.now()}`
  }
}

function updateHud(): void {
  if (!import.meta.env.DEV) return
  if (!hudEl) {
    hudEl = document.createElement('div')
    hudEl.id = 'qa-web-vitals-hud'
    hudEl.setAttribute('aria-hidden', 'true')
    Object.assign(hudEl.style, {
      position: 'fixed',
      right: '8px',
      bottom: '8px',
      zIndex: '99999',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: '10px',
      lineHeight: '1.35',
      padding: '6px 8px',
      borderRadius: '6px',
      color: '#94a3b8',
      background: 'rgba(9,9,11,0.82)',
      border: '1px solid rgba(255,255,255,0.1)',
      pointerEvents: 'none',
      whiteSpace: 'pre',
    })
    document.body.appendChild(hudEl)
  }
  const fmt = (v: number | undefined, digits = 0) =>
    v == null ? '-' : v.toFixed(digits)
  hudEl.textContent =
    `Web Vitals\n` +
    `LCP ${fmt(snapshot.lcpMs)}ms  CLS ${fmt(snapshot.cls, 3)}\n` +
    `INP ${fmt(snapshot.inpMs)}ms  TTFB ${fmt(snapshot.ttfbMs)}ms`
}

async function flushHeartbeat(): Promise<void> {
  const body = {
    platform: 'web',
    appVersion: APP_VERSION,
    deviceId: getDeviceId(),
    lcpMs: snapshot.lcpMs,
    cls: snapshot.cls,
    inpMs: snapshot.inpMs,
    ttfbMs: snapshot.ttfbMs,
    timestamp: Date.now(),
  }
  try {
    await fetch(`${API_BASE_URL}/client/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
      keepalive: true,
    })
  } catch (e) {
    logger.warn('web_vitals_heartbeat_failed', { error: String(e) })
  }
}

function scheduleReport(): void {
  if (reportTimer) clearTimeout(reportTimer)
  // 合并短时间多次 vital 回调，避免打爆心跳接口
  reportTimer = setTimeout(() => {
    void flushHeartbeat()
  }, 2500)
}

function onMetric(metric: Metric): void {
  const name = metric.name
  if (name === 'LCP') snapshot.lcpMs = metric.value
  else if (name === 'CLS') snapshot.cls = metric.value
  else if (name === 'INP') snapshot.inpMs = metric.value
  else if (name === 'TTFB') snapshot.ttfbMs = metric.value

  logger.info(`web_vital_${name.toLowerCase()}`, {
    value: metric.value,
    rating: metric.rating,
    id: metric.id,
  })
  updateHud()
  scheduleReport()
}

/** 在 main.tsx 入口调用一次 */
export function initWebVitals(): void {
  if (typeof window === 'undefined') return
  onLCP(onMetric)
  onCLS(onMetric)
  onINP(onMetric)
  onTTFB(onMetric)

  // 页面隐藏时尽量打一次，减少样本丢失
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      void flushHeartbeat()
    }
  })
}

export function getWebVitalSnapshot(): WebVitalSnapshot {
  return { ...snapshot }
}
