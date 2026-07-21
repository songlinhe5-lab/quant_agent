/**
 * 选股器 WebSocket 实时行情推送 Hook
 * 管理 WS 连接生命周期、自动重连、Token 续期、订阅/退订
 */

import { useEffect, useRef } from 'react'
import { getValidAccessToken } from '@/lib/api-client'
import { market } from '@/lib/proto/market'
import { useKeepAliveActive } from '@/components/layout/keep-alive-outlet'
import { useBackendStatusStore } from '@/stores/useBackendStatusStore'

/**
 * 建立并管理选股器 WS 连接，根据 pageSymbols 自动订阅/退订
 */
export function useScreenerWs(pageSymbols: string[]) {
  const wsRef = useRef<WebSocket | null>(null)
  const prevSymbolsRef = useRef<string[]>([])
  const isMountedRef = useRef(true)
  const wsOpenedRef = useRef(false)
  const keepAliveActive = useKeepAliveActive()

  // WS 连接管理
  useEffect(() => {
    isMountedRef.current = true;
    let reconnectTimer: NodeJS.Timeout;
    const connectWS = async () => {
      if (!keepAliveActive || document.visibilityState !== 'visible') return;
      const token = await getValidAccessToken();
      if (!token) { console.warn('[Screener WS] 无有效 token，跳过连接'); return; }
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      try {
        wsRef.current = new WebSocket(`${wsProtocol}//${window.location.host}/api/v1/market/quotes/ws?token=${token}`);
      } catch (err) {
        useBackendStatusStore.getState().registerFailure('Market WebSocket 连接失败')
        console.error('[Screener WS] WebSocket 构造失败:', err);
        return;
      }
      wsRef.current.binaryType = "arraybuffer";
      wsRef.current.onopen = () => {
        if (!isMountedRef.current) return;
        wsOpenedRef.current = true;
        useBackendStatusStore.getState().registerSuccess()
        const pureTickers = prevSymbolsRef.current.map((s: string) => s.replace(/^(US|HK|SH|SZ)\./, ''));
        if (pureTickers.length > 0) wsRef.current!.send(JSON.stringify({ action: 'subscribe', tickers: pureTickers }));
      };
      wsRef.current.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          if (event.data instanceof ArrayBuffer) {
            const q = market.QuoteData.decode(new Uint8Array(event.data));
            window.dispatchEvent(new CustomEvent('screener_quote_update', { detail: { ticker: q.ticker, last_price: q.lastPrice ?? (q as any).last_price ?? 0, change_pct: q.changePct ?? (q as any).change_pct ?? "0.0%" } }));
          }
        } catch (e) { /* ignore decode error */ }
      };
      wsRef.current.onerror = () => {
        useBackendStatusStore.getState().registerFailure('Market WebSocket 连接失败')
        console.warn('[Screener WS] 连接错误，等待 onclose 触发重连（后端可能不可达）')
      };
      wsRef.current.onclose = (ev?: CloseEvent) => {
        wsOpenedRef.current = false;
        if (!isMountedRef.current) return;
        if (ev) console.warn(`[Screener WS] 连接关闭 code=${ev.code} reason=${ev.reason || '(空)'}`);
        reconnectTimer = setTimeout(connectWS, 1000);
      };
    };
    connectWS();
    const handleOnlineWS = () => { if (wsRef.current) wsRef.current.close(); };
    window.addEventListener('online', handleOnlineWS);
    const handleVisibilityOrActive = () => {
      if (!isMountedRef.current) return
      if (!keepAliveActive || document.visibilityState !== 'visible') {
        if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close(); wsRef.current = null }
      } else {
        connectWS()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityOrActive)
    return () => { isMountedRef.current = false; clearTimeout(reconnectTimer); window.removeEventListener('online', handleOnlineWS); document.removeEventListener('visibilitychange', handleVisibilityOrActive); if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close(); } };
  }, [keepAliveActive]);

  // 订阅/退订管理
  useEffect(() => {
    const currentSymbols = pageSymbols;
    const prevSymbols = prevSymbolsRef.current;
    const toUnsubscribe = prevSymbols.filter(s => !currentSymbols.includes(s)).map(s => s.replace(/^(US|HK|SH|SZ)\./, ''));
    const toSubscribe = currentSymbols.filter(s => !prevSymbols.includes(s)).map(s => s.replace(/^(US|HK|SH|SZ)\./, ''));
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      if (toUnsubscribe.length > 0) wsRef.current.send(JSON.stringify({ action: 'unsubscribe', tickers: toUnsubscribe }));
      if (toSubscribe.length > 0) wsRef.current.send(JSON.stringify({ action: 'subscribe', tickers: toSubscribe }));
    }
    prevSymbolsRef.current = currentSymbols;
  }, [pageSymbols.join(',')]);
}
