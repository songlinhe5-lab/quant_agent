import { useState, useEffect, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient, API_BASE_URL, getAccessToken } from '@/lib/api-client'
import { market } from '@/lib/proto/market'
import { WatchlistItem } from '@/stores/use-watchlist'

interface UseMarketDataProps {
  selectedSymbol: string;
  selectedPeriod: string;
  watchlist: WatchlistItem[];
  updateTicker: (sym: string, data: any) => void;
}

export function useMarketData({ selectedSymbol, selectedPeriod, watchlist, updateTicker }: UseMarketDataProps) {
  const { toast } = useToast()
  const [realQuote, setRealQuote] = useState<any>(null)
  const [realHistory, setRealHistory] = useState<any[]>([])
  const [gatewayStatus, setGatewayStatus] = useState<string>('DISCONNECTED')
  const [isStale, setIsStale] = useState(false)

  const latestStatsRef = useRef<Record<string, { change: number, vol: number }>>({})
  const lastWsUpdateTime = useRef<number>(0)
  const staleTimerRef = useRef<NodeJS.Timeout | null>(null)
  const syncErrorToastShown = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const wsConnectedRef = useRef(false)

  // ⏳ 1. 拉取低频 K 线图历史与底层运行状态
  useEffect(() => {
    let isMounted = true

    async function fetchMarketData(isInitial = false) {
      if (watchlist.length === 0) {
        if (isMounted) setRealHistory([])
        return
      }

      if (isInitial && isMounted) {
        setRealHistory([]) // 切换标的或周期时，先清空数据防止错觉
      }

      try {
        const sym = selectedSymbol.replace('/', '')
        const ktypeMap: Record<string, string> = { '1m': 'K_1M', '5m': 'K_5M', '15m': 'K_15M', '1h': 'K_60M', '4h': 'K_60M', '1d': 'K_DAY', '1w': 'K_WEEK' }
        const ktype = ktypeMap[selectedPeriod] || 'K_60M'
        
        const [statusRes, histRes] = await Promise.all([
          apiClient.get('/market/futu/status').catch(() => null),
          apiClient.get('/market/history', { ticker: sym, ktype, num: 300 }).catch(() => null)
        ])

        if (isMounted && statusRes?.data) {
          setGatewayStatus(statusRes.data.status)
        }
        
        if (isMounted && histRes?.data?.status === 'success' && histRes.data.data) {
          const historyData = histRes.data.data
          setRealHistory(historyData)
          
          if (historyData.length > 1) {
            const recent = historyData.slice(-20)
            const sparkDir: number[] = []
            for (let i = 1; i < recent.length; i++) {
              const prev = recent[i - 1].close
              const curr = recent[i].close
              sparkDir.push(((curr - prev) / prev) * 100)
            }
            updateTicker(selectedSymbol, { sparkDir })
          }
        }
        syncErrorToastShown.current = false
      } catch (e) {
        console.error('Market data fetch error:', e)
        if (!syncErrorToastShown.current) {
          toast({ variant: 'destructive', title: '行情数据断连', description: '无法获取最新 K 线与网关状态，已切换为离线模式。' })
          syncErrorToastShown.current = true
        }
      }
    }
    
    fetchMarketData(true)
    const iv = setInterval(() => fetchMarketData(false), 15000)

    const handleOnline = () => { fetchMarketData(false) }
    window.addEventListener('online', handleOnline)

    return () => { 
      isMounted = false
      clearInterval(iv)
      window.removeEventListener('online', handleOnline)
    }
  }, [selectedSymbol, selectedPeriod, watchlist.length, updateTicker, toast])

  // 🚀 2. 建立高频 WebSocket 行情订阅 (Protobuf 解码)
  useEffect(() => {
    let isMounted = true

    function connectWS() {
      if (watchlist.length === 0) return

      // 无 token 时不建立连接，避免 403 无限重连
      const token = getAccessToken()
      if (!token) {
        console.warn('[WS] 无认证 token，跳过 WebSocket 连接')
        return
      }

      // Close existing connection
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }

      const sym = selectedSymbol.replace('/', '')
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = API_BASE_URL.startsWith('http') 
        ? API_BASE_URL.replace(/^http/, 'ws') + '/market/quotes/ws?token=' + token
        : `${protocol}//${window.location.host}${API_BASE_URL}/market/quotes/ws?token=` + token
      
      const ws = new WebSocket(wsUrl)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        wsConnectedRef.current = true
        if (isMounted) {
          const allTickers = Array.from(new Set([sym, ...watchlist.map(w => w.symbol.replace('/', ''))]))
          ws.send(JSON.stringify({ action: 'subscribe', tickers: allTickers }))
        }
      }

      ws.onerror = () => {
        // Connection error - will trigger onclose
      }

      ws.onclose = () => {
        wsConnectedRef.current = false
        // Auto-reconnect after 3 seconds if still mounted
        if (isMounted && watchlist.length > 0) {
          setTimeout(() => {
            if (isMounted && !wsConnectedRef.current) {
              connectWS()
            }
          }, 3000)
        }
      }

      ws.onmessage = (event) => {
        if (!isMounted) return
        try {
          if (event.data instanceof ArrayBuffer) {
            const q = market.QuoteData.decode(new Uint8Array(event.data))
            const lastPrice = q.lastPrice ?? (q as any).last_price ?? 0
            const detail = { ticker: q.ticker, last_price: lastPrice, change_pct: q.changePct ?? (q as any).change_pct ?? "0.0%", volume_str: q.volumeStr ?? (q as any).volume_str ?? "--", bids: Array.isArray(q.bids) ? q.bids : [], asks: Array.isArray(q.asks) ? q.asks : [], source: q.source, status: q.status }

            const symClean = (s => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, ''))(q.ticker);
            let volNum = 0;
            const vStr = q.volumeStr ?? (q as any).volume_str;
            if (typeof vStr === 'string') {
              const baseNum = parseFloat(vStr.replace(/[^0-9.]/g, '')) || 0;
              if (vStr.includes('T') || vStr.includes('万亿')) volNum = baseNum * 1e12;
              else if (vStr.includes('B') || vStr.includes('亿')) volNum = baseNum * 1e9;
              else if (vStr.includes('M')) volNum = baseNum * 1e6;
              else if (vStr.includes('万')) volNum = baseNum * 1e4;
              else if (vStr.includes('K')) volNum = baseNum * 1e3;
              else volNum = baseNum;
            } else if (typeof vStr === 'number') volNum = vStr;
            latestStatsRef.current[symClean] = { change: parseFloat(q.changePct ?? (q as any).change_pct) || 0, vol: volNum };

            window.dispatchEvent(new CustomEvent('quote_update', { detail }))
            window.dispatchEvent(new CustomEvent('market_tick', { detail }))

            const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
            if (cleanSym(q.ticker) === cleanSym(selectedSymbol)) {
              const now = Date.now()
              if (now - lastWsUpdateTime.current > 300 && !document.hidden) { setRealQuote(detail); lastWsUpdateTime.current = now }
              if (staleTimerRef.current) clearTimeout(staleTimerRef.current)
              setIsStale(false)
              staleTimerRef.current = setTimeout(() => setIsStale(true), 15000)
            }
          }
        } catch (e) { /* ignore decode error */ }
      }
    }

    connectWS()
    const handleOnlineWS = () => { 
      if (wsRef.current) wsRef.current.close()
      setTimeout(() => { if (isMounted) connectWS() }, 500) 
    }
    window.addEventListener('online', handleOnlineWS)

    return () => {
      isMounted = false
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        const sym = selectedSymbol.replace('/', '')
        wsRef.current.send(JSON.stringify({ action: 'unsubscribe', tickers: [sym] }))
      }
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current)
      window.removeEventListener('online', handleOnlineWS)
      // Only close if OPEN - let CONNECTING sockets finish or fail naturally
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close()
      }
      wsRef.current = null
    }
  }, [selectedSymbol, watchlist.length])

  return { realQuote, realHistory, setRealHistory, gatewayStatus, isStale, latestStatsRef }
}