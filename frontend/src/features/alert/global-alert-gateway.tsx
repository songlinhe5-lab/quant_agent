'use client'

import { useCallback, useEffect } from 'react'
import { useAlertWebSocket } from '@/hooks/use-alert-api'
import { useAlertOverlayStore } from '@/stores/useAlertOverlayStore'
import { parseAlertPush } from './alert-nav'
import { AlertOverlay } from './alert-overlay'
import { AlertToastStack } from './alert-toast-stack'
import logger from '@/lib/logger'

/**
 * DashboardLayout 级告警网关：常驻 WS → P0 Overlay / P1-P2 Toast / P3 角标
 */
export function GlobalAlertGateway() {
  const enqueuePush = useAlertOverlayStore((s) => s.enqueuePush)
  const setWsStale = useAlertOverlayStore((s) => s.setWsStale)

  const onEvent = useCallback(
    (raw: unknown) => {
      const payload = parseAlertPush(raw)
      if (!payload) {
        logger.warn('[AlertGateway] 无法解析推送', { raw: String(raw).slice(0, 120) })
        return
      }
      enqueuePush(payload)
    },
    [enqueuePush],
  )

  const onStatus = useCallback(
    (connected: boolean) => {
      setWsStale(!connected)
    },
    [setWsStale],
  )

  const { connect } = useAlertWebSocket(onEvent, onStatus)

  useEffect(() => {
    connect()
  }, [connect])

  return (
    <>
      <AlertOverlay />
      <AlertToastStack />
    </>
  )
}
