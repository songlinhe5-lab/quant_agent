import { useState, useEffect, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient, getValidAccessToken, getWsBaseUrl } from '@/lib/api-client'
import { market } from '@/lib/proto/market'
import { WatchlistItem } from '@/stores/use-watchlist'
import { useKeepAliveActive } from '@/components/layout/keep-alive-context'

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
        // 💡 加密货币规范化：BTC/USD -> BTC-USD（与系统 YFinance 约定对齐，避免后端 format_yf_ticker 不识别 BTCUSD 而 400）
        const rawSym = selectedSymbol.replace('/', '')
        const sym = /^(BTC|ETH|SOL|BNB|USDC?|USDT|XRP|DOGE|ADA|AVAX|TON|TRX|DOT|MATIC|LTC|LINK|NEAR|APT|ARB|OP|INJ|SUI|STX|IMX|FIL|ETC|ATOM|UNI|LDO|CRV|MKR|SAND|AXS|MANA|THETA|EGLD|FTM|ALGO|HBAR|VET|ICP|FLOW|CHZ|ENJ|GALA|SUSHI|COMP|AAVE|SNX|YFI|1INCH|BCH|EOS|XLM|XMR|ZEC|DASH|WAVES|KAVA|RUNE|KSM|CELO|FLOW)USD$/i.test(rawSym)
          ? rawSym.slice(0, -3) + '-USD'
          : rawSym
        const ktypeMap: Record<string, string> = {
          '1m': 'K_1M',    // 分时图
          'tick': 'K_1M',  // Tick图 (实时折线图，不需要历史数据)
          '5m': 'K_5M',    // 5日图
          '15m': 'K_15M',  // 15分钟
          '1h': 'K_60M',   // 1小时
          '4h': 'K_60M',   // 4小时
          '1d': 'K_DAY',   // 日K
          '1w': 'K_WEEK',  // 周K
          '1M': 'K_MONTH', // 月K
        }
        // 💡 日线及以上周期拉取最长历史数据，用于充分展示长期趋势
        const historyNumMap: Record<string, number> = {
          '1m': 300,
          'tick': 300,
          '5m': 300,
          '15m': 300,
          '1h': 300,
          '4h': 300,
          '1d': 1000,  // 日K: 约4年数据 (Futu API 最大1000条)
          '1w': 1000,  // 周K: 约20年数据
          '1M': 1000,  // 月K: 约80年数据
        }
        const ktype = ktypeMap[selectedPeriod] || 'K_60M'
        const num = historyNumMap[selectedPeriod] || 300

        const [statusRes, histRes] = await Promise.all([
          apiClient.get('/market/futu/status').catch(() => null),
          apiClient.get('/market/history', { ticker: sym, ktype, num }).catch(() => null)
        ])

        if (isMounted && statusRes?.data) {
          setGatewayStatus(statusRes.data.status)
        }

        // BE-13 方案 B: /history 返回扁平 payload {data:[...], source, degraded}（list 包入 data 键）
        // 统一由 response_envelope_middleware 包成 {code,msg,data,ts}，apiClient 解包后 res.data 即该 payload
        if (isMounted && histRes?.data?.data) {
          let historyData = histRes.data.data
          // 防御: 后端偶发嵌套信封 (data.data 仍是 {status,data} 结构) 会触发 .slice 崩溃
          if (!Array.isArray(historyData) && historyData?.data) {
            historyData = historyData.data
          }
          setRealHistory(historyData)

          if (Array.isArray(historyData) && historyData.length > 1) {
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
    // PERF-01: 移除 15s 全量轮询（改为下方 30s 对账 + 5s 增量），减少主线程全量重建压力
    const reconciliationIv = setInterval(() => fetchMarketData(false), 30000)

    const handleOnline = () => { fetchMarketData(false) }
    window.addEventListener('online', handleOnline)

    return () => {
      isMounted = false
      clearInterval(reconciliationIv)
      window.removeEventListener('online', handleOnline)
    }
  }, [selectedSymbol, selectedPeriod, watchlist.length, updateTicker, toast])

  // PERF-01: 轻量增量 —— 高频轮询 quant:kline 增量，新 K 线时由图表真正 append
  // 替代原来的 15s 全量重拉，避免每次全量 setData(1000 根 + 14 series) 造成的卡顿。
  useEffect(() => {
    let isMounted = true
    let inFlight = false

    async function pollKlineIncremental() {
      if (inFlight || watchlist.length === 0) return
      const sym = selectedSymbol.replace('/', '')
      if (!sym) return
      inFlight = true
      try {
        const res = await apiClient.get(`/market/kline/${encodeURIComponent(sym)}`).catch(() => null)
        if (!isMounted || !res?.data) return
        const kline = res.data.kline
        if (!kline || (typeof kline.time !== 'string' && typeof kline.time !== 'number')) return
        // 事件携带最新一根 K 线（time/open/high/low/close/volume），图表按 time 判定更新 or 追加
        window.dispatchEvent(new CustomEvent('kline_incremental', {
          detail: { ticker: sym, kline },
        }))
      } catch (_e) {
        /* 忽略：增量失败静默，下一轮对账兜底 */
      } finally {
        inFlight = false
      }
    }

    pollKlineIncremental()
    const iv = setInterval(pollKlineIncremental, 5000)
    return () => {
      isMounted = false
      clearInterval(iv)
    }
  }, [selectedSymbol, watchlist.length])

  // 💡 3. 从 Redis 缓存批量获取自选列表行情（非聚焦 ticker 使用）
  useEffect(() => {
    let isMounted = true

    async function fetchWatchlistQuotes() {
      if (watchlist.length === 0) return

      // 💡 排除当前聚焦的 ticker（它通过 WebSocket 获取实时数据）
      const nonFocusedTickers = watchlist
        .map(w => w.symbol.replace('/', ''))
        .filter(s => s !== selectedSymbol.replace('/', ''))

      if (nonFocusedTickers.length === 0) return

      try {
        const res = await apiClient.post('/market/quotes/batch', { tickers: nonFocusedTickers })
        if (isMounted && res.data?.status === 'success' && res.data.data) {
          // 💡 更新 latestStatsRef 用于排序和显示
          Object.entries(res.data.data).forEach(([ticker, data]: [string, any]) => {
            if (data.status === 'CACHED') {
              const cleanSym = ticker.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
              const changePct = parseFloat(String(data.change_pct).replace('%', '')) || 0
              latestStatsRef.current[cleanSym] = {
                change: changePct,
                vol: 0  // Redis 缓存中可能没有成交量数据
              }
              // 💡 触发自定义事件更新 watchlist 显示
              window.dispatchEvent(new CustomEvent('quote_update', {
                detail: {
                  ticker,
                  last_price: data.last_price,
                  change_pct: data.change_pct,
                  volume_str: data.volume_str,
                  source: 'redis_cache',
                  status: 'CACHED'
                }
              }))
            }
          })
        }
      } catch (e) {
        console.error('Watchlist batch fetch error:', e)
      }
    }

    fetchWatchlistQuotes()
    // 💡 每 30 秒刷新一次自选列表缓存数据
    const iv = setInterval(fetchWatchlistQuotes, 30000)

    return () => {
      isMounted = false
      clearInterval(iv)
    }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol, watchlist.length])

  // 🚀 2. 建立高频 WebSocket 行情订阅 (Protobuf 解码)
  const keepAliveActive = useKeepAliveActive()
  useEffect(() => {
    let isMounted = true

    async function connectWS() {
      if (watchlist.length === 0) return

      // 💡 keep-alive 后台模块 / 页面隐藏时不建立 WS，避免多模块 WS 并发重连风暴
      if (!keepAliveActive || document.visibilityState !== 'visible') return

      // 统一 Token 获取：内部自动处理过期检测 + Refresh 续期
      const token = await getValidAccessToken()
      if (!token) {
        console.warn('[WS] 无有效 token，跳过 WebSocket 连接')
        return
      }

      // Close existing connection
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }

      const sym = selectedSymbol.replace('/', '')
      const wsUrl = `${getWsBaseUrl()}/api/v1/market/quotes/ws?token=` + token

      const ws = new WebSocket(wsUrl)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        wsConnectedRef.current = true
        if (isMounted) {
          // 💡 只订阅当前聚焦的 ticker，非聚焦的 ticker 不订阅
          ws.send(JSON.stringify({ action: 'subscribe', tickers: [sym] }))
        }
      }

      ws.onerror = () => {
        // Connection error - will trigger onclose
      }

      ws.onclose = (ev?: CloseEvent) => {
        const _wasConnected = wsConnectedRef.current
        wsConnectedRef.current = false
        if (ev) console.warn(`[WS] 连接关闭 code=${ev.code} reason=${ev.reason || '(空)'}`)
        // Auto-reconnect after 3 seconds if still mounted
        if (isMounted && watchlist.length > 0) {
          setTimeout(() => {
            if (!isMounted || wsConnectedRef.current) return
            connectWS()
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
            // Level 2 DOM（OrderBookWebGL）监听 'orderbook' 事件，需单独派发，否则盘口深度不渲染
            window.dispatchEvent(new CustomEvent('orderbook', { detail }))

            const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
            if (cleanSym(q.ticker) === cleanSym(selectedSymbol)) {
              const now = Date.now()
              if (now - lastWsUpdateTime.current > 300 && !document.hidden) { setRealQuote(detail); lastWsUpdateTime.current = now }
              if (staleTimerRef.current) clearTimeout(staleTimerRef.current)
              setIsStale(false)
              staleTimerRef.current = setTimeout(() => setIsStale(true), 30000)
            }
          }
        } catch (_e) { /* ignore decode error */ }
      }
    }

    connectWS()
    const handleOnlineWS = () => {
      if (!keepAliveActive || document.visibilityState !== 'visible') return
      if (wsRef.current) wsRef.current.close()
      setTimeout(() => { if (isMounted) connectWS() }, 500)
    }
    window.addEventListener('online', handleOnlineWS)
    // 💡 页面可见性 / keep-alive 激活态变化：隐藏或后台时断 WS，恢复时重连
    const handleVisibilityOrActive = () => {
      if (!isMounted) return
      if (!keepAliveActive || document.visibilityState !== 'visible') {
        if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close(); wsRef.current = null }
      } else {
        connectWS()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityOrActive)

    return () => {
      isMounted = false
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        const sym = selectedSymbol.replace('/', '')
        // 💡 取消订阅当前聚焦的 ticker
        wsRef.current.send(JSON.stringify({ action: 'unsubscribe', tickers: [sym] }))
      }
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current)
      window.removeEventListener('online', handleOnlineWS)
      document.removeEventListener('visibilitychange', handleVisibilityOrActive)
      // Only close if OPEN - let CONNECTING sockets finish or fail naturally
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close()
      }
      wsRef.current = null
    }
  }, [selectedSymbol, watchlist.length, keepAliveActive])

  return { realQuote, realHistory, setRealHistory, gatewayStatus, isStale, latestStatsRef }
}
