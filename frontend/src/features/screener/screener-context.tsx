'use client'

import React, { createContext, useContext, useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useToast } from '@/hooks/use-toast'
import { useWatchlist } from '@/stores/use-watchlist'
import { apiClient, getAccessToken, refreshAccessToken, isTokenExpired } from '@/lib/api-client'
import { market } from '@/lib/proto/market'
import { useKeepAliveActive } from '@/components/layout/keep-alive-outlet'
import { getZhLabel, formatDisplaySymbol, type SortKey } from '@/features/screener/shared'

export interface ScreenerHistory {
  nlp: string;
  dsl: string;
  time: number;
}

interface ScreenerContextType {
  nlpQuery: string; setNlpQuery: (v: string) => void;
  isLoading: boolean; setIsLoading: (v: boolean) => void;
  progress: number; setProgress: (v: number) => void;
  scanStatus: string; setScanStatus: (v: string) => void;
  dslQuery: string; setDslQuery: (v: string) => void;
  results: any[]; setResults: (v: any[]) => void;
  selected: string[]; setSelected: (v: string[] | ((prev: string[]) => string[])) => void;
  sortKey: SortKey; setSortKey: (v: SortKey) => void;
  sortDir: 1 | -1; setSortDir: (v: 1 | -1) => void;
  showSubManager: boolean; setShowSubManager: (v: boolean) => void;
  currentPage: number; setCurrentPage: (v: number) => void;
  pageSize: number; setPageSize: (v: number) => void;
  totalItems: number; setTotalItems: (v: number) => void;
  history: ScreenerHistory[]; setHistory: (v: ScreenerHistory[]) => void;
  showHistory: boolean; setShowHistory: (v: boolean) => void;
  placeholderText: string; setPlaceholderText: (v: string) => void;
  displayPrompts: string[]; setDisplayPrompts: (v: string[]) => void;
  showRawDsl: boolean; setShowRawDsl: (v: boolean) => void;
  showRagDict: boolean; setShowRagDict: (v: boolean) => void;
  previewData: {symbol: string, price?: number, change?: number} | null; setPreviewData: (v: any) => void;
  columnFilters: Record<string, { min: string, max: string }>; setColumnFilters: (v: any) => void;
  dynamicCols: string[];
  paginatedData: any[];
  realDataLength: number;
  totalPages: number;
  isAllCurrentPageSelected: boolean;
  pageSymbols: string[];
  handleApplyFilter: (col: string, range: { min: string, max: string }) => void;
  handleClearFilter: (col: string) => void;
  refreshPrompts: () => void;
  fetchPageData: (dsl: string, page: number, size: number, sKey: string, sDir: number, filters?: Record<string, any>) => void;
  handleSort: (key: SortKey) => void;
  toggleAll: (checked: boolean) => void;
  toggleOne: (sym: string, checked: boolean) => void;
  handleExportCSV: () => void;
  handleAddSingle: (sym: string) => void;
  handleAddBatch: () => void;
  handleAddAndOpen: (sym: string) => void;
  handleSendToCopilot: (sym: string) => void;
  handleSendToBacktest: (sym: string) => void;
  handleSubscribe: () => void;
  handleTranslate: (overrideQuery?: string | any) => void;
}

const ScreenerContext = createContext<ScreenerContextType | null>(null)

export function useScreenerContext() {
  const context = useContext(ScreenerContext)
  if (!context) throw new Error('useScreenerContext must be used within ScreenerProvider')
  return context
}

export function ScreenerProvider({ children }: { children: React.ReactNode }) {
  const { toast } = useToast()
  const addTicker = useWatchlist((state) => state.addTicker)
  const [nlpQuery, setNlpQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [scanStatus, setScanStatus] = useState('')
  const [dslQuery, setDslQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [sortKey, setSortKey] = useState<SortKey>('mktcap')
  const [sortDir, setSortDir] = useState<1 | -1>(-1)
  const [showSubManager, setShowSubManager] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalItems, setTotalItems] = useState(0)
  const [history, setHistory] = useState<ScreenerHistory[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [placeholderText, setPlaceholderText] = useState('告诉 Agent 您的选股逻辑，例如：寻找今日 RSI 超卖且内资大幅流入的港股科技股...')
  const [displayPrompts, setDisplayPrompts] = useState<string[]>([])
  const [showRawDsl, setShowRawDsl] = useState(false)
  const [showRagDict, setShowRagDict] = useState(false)
  const [previewData, setPreviewData] = useState<{symbol: string, price?: number, change?: number} | null>(null)
  const [columnFilters, setColumnFilters] = useState<Record<string, { min: string, max: string }>>({})

  const handleApplyFilter = (col: string, range: { min: string, max: string }) => {
    if (!range.min && !range.max) {
      handleClearFilter(col)
    } else {
      setColumnFilters(prev => {
        const next = { ...prev, [col]: range }
        if (dslQuery) fetchPageData(dslQuery, 1, pageSize, sortKey, sortDir, next)
        return next
      })
      setCurrentPage(1)
    }
  }
  const handleClearFilter = (col: string) => {
    setColumnFilters(prev => { const next = { ...prev }; delete next[col]; if (dslQuery) fetchPageData(dslQuery, 1, pageSize, sortKey, sortDir, next); return next })
    setCurrentPage(1)
  }

  const refreshPrompts = async () => {
    try {
      const res = await apiClient.get('/screener/suggestions?limit=6');
      if (res.data?.status === 'success' && res.data.data?.length > 0) {
        setDisplayPrompts(res.data.data);
        setPlaceholderText(`告诉 Agent 您的选股逻辑，例如：${res.data.data[res.data.data.length - 1]}...`);
      }
    } catch (e) {
      const fallback = ["格雷厄姆深度价值股", "MACD在水上金叉，且量比大于2的强势突破", "A股中报业绩预增，净利润同比增长超50%", "PE历史百分位低于10%极度低估的美股", "连续三天放量，且股价突破52周新高", "港美双市场极度恐慌错杀"];
      setDisplayPrompts(fallback);
      setPlaceholderText(`告诉 Agent 您的选股逻辑，例如：${fallback[0]}...`);
    }
  }

  useEffect(() => { refreshPrompts() }, [])

  useEffect(() => {
    if (!dslQuery) return;
    const interval = setInterval(() => {
      if (document.hidden) return;
      apiClient.post('/screener/run', {
        dsl: dslQuery, page: 1, page_size: 1, 
        sort_key: sortKey === 'rank' ? 'mktcap' : sortKey, 
        sort_dir: sortDir, filters: columnFilters
      }).catch(() => {});
    }, 4 * 60 * 1000);
    return () => clearInterval(interval);
  }, [dslQuery, sortKey, sortDir, columnFilters]);

  const fetchPageData = async (dsl: string, page: number, size: number, sKey: string, sDir: number, filters: Record<string, any> = {}) => {
    setIsLoading(true);
    setScanStatus('从云端获取中...');
    const validDsl = dsl;
    try {
      JSON.parse(dsl);
    } catch (e) {
      if (nlpQuery && nlpQuery.trim()) {
        toast({ title: '检测到缓存数据异常', description: '正在重新解析您的查询条件...' });
        await handleTranslate(nlpQuery);
        return;
      } else {
        toast({ variant: 'destructive', title: 'DSL 格式错误', description: '缓存的筛选条件已损坏。请重新输入自然语言查询或选择历史记录。' });
        setIsLoading(false);
        setScanStatus('');
        return;
      }
    }
    
    try {
      const res = await apiClient.post('/screener/run', {
        dsl: validDsl, page, page_size: size,
        sort_key: sKey === 'rank' ? 'mktcap' : sKey,
        sort_dir: sDir, filters
      });
      if (res.data?.status === 'success' && res.data.data) {
        setResults(res.data.data);
        setTotalItems(res.data.total || res.data.data.length);
      } else {
        toast({ variant: 'destructive', title: '拉取失败', description: res.data?.message });
      }
    } catch (error: any) {
      toast({ variant: 'destructive', title: '网络异常', description: error.message });
    } finally {
      setIsLoading(false);
      setScanStatus('');
    }
  };

  useEffect(() => {
    try {
      const h = localStorage.getItem('quant_screener_history')
      if (h) setHistory(JSON.parse(h))
    } catch (e) { /* ignore parse error */ }
    try {
      const latestStateStr = localStorage.getItem('quant_screener_latest_state')
      if (latestStateStr) {
        const latestState = JSON.parse(latestStateStr)
        if (latestState.results && latestState.results.length > 0) {
          let isValidDsl = false;
          try { JSON.parse(latestState.dslQuery || ''); isValidDsl = true; } catch (e) { localStorage.removeItem('quant_screener_latest_state'); }
          if (isValidDsl) {
            setResults(latestState.results)
            setTotalItems(latestState.totalItems || latestState.results.length)
            setNlpQuery(latestState.nlpQuery || '')
            setDslQuery(latestState.dslQuery || '')
          }
        }
      }
    } catch (e) { /* ignore parse error */ }
    const fetchCloudHistory = async () => {
      try {
        const res = await apiClient.get('/screener/history')
        if (res.data?.status === 'success' && res.data.data && res.data.data.length > 0) {
          setHistory(res.data.data)
          localStorage.setItem('quant_screener_history', JSON.stringify(res.data.data))
        }
      } catch (e) { /* ignore network error */ }
    }
    fetchCloudHistory()
  }, [])

  const handleSort = (key: SortKey) => {
    if (isLoading) return;
    const newDir = sortKey === key ? (sortDir === 1 ? -1 : 1) : -1;
    setSortKey(key);
    setSortDir(newDir);
    setCurrentPage(1);
    if (dslQuery) fetchPageData(dslQuery, 1, pageSize, key, newDir, columnFilters);
  }

  const dynamicCols = useMemo(() => {
    if (results.length === 0) return []
    const keys = new Set<string>()
    results.forEach(r => Object.keys(r).forEach(k => { if (!['symbol', 'name', 'rank'].includes(k)) keys.add(k) }))
    return Array.from(keys).sort()
  }, [results])

  const paginatedData = [...results]
  const realDataLength = totalItems
  const totalPages = Math.ceil(totalItems / pageSize)
  const pageSymbols = paginatedData.map(r => r.symbol)
  const isAllCurrentPageSelected = pageSymbols.length > 0 && pageSymbols.every(r => selected.includes(r))
  
  const toggleAll = (checked: boolean) => {
    if (checked) setSelected((prev) => Array.from(new Set([...prev, ...pageSymbols])))
    else setSelected((prev) => prev.filter((s) => !pageSymbols.includes(s)))
  }
  const toggleOne = (sym: string, checked: boolean) => setSelected((prev) => checked ? [...prev, sym] : prev.filter((s) => s !== sym))

  const handleExportCSV = async () => {
    if (!dslQuery) { toast({ title: '没有数据可导出', variant: 'destructive' }); return; }
    toast({ title: '正在生成导出文件...', description: '正在从云端拉取全量数据' })
    try {
      const res = await apiClient.post('/screener/run', { dsl: dslQuery, page: 1, page_size: 0, sort_key: sortKey === 'rank' ? 'mktcap' : sortKey, sort_dir: sortDir, filters: columnFilters });
      if (res.data?.status === 'success' && res.data.data) {
        const fullData = res.data.data;
        if (fullData.length === 0) { toast({ title: '没有数据可导出', variant: 'destructive' }); return; }
        const headers = ['rank', 'symbol', 'name', ...dynamicCols]
        const csvRows = [headers.map(h => `"${getZhLabel(h) || h}"`).join(',')]
        fullData.forEach((row: any) => { csvRows.push(headers.map(col => row[col] === null || row[col] === undefined ? '""' : `"${String(row[col]).replace(/"/g, '""')}"`).join(',')) })
        const blob = new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url;
        a.download = `QuantEdge_Screener_${new Date().toISOString().slice(0, 10)}.csv`; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
        toast({ title: '导出成功', description: `已为您导出全量 ${fullData.length} 条选股结果。` })
      }
    } catch (e) { toast({ title: '导出失败', description: '获取全量数据异常', variant: 'destructive' }) }
  }

  const wsRef = useRef<WebSocket | null>(null);
  const prevSymbolsRef = useRef<string[]>([]);
  const isMountedRef = useRef(true);
  const wsOpenedRef = useRef(false);
  const keepAliveActive = useKeepAliveActive();

  useEffect(() => {
    isMountedRef.current = true;
    let reconnectTimer: NodeJS.Timeout;
    const connectWS = async () => {
      // 💡 keep-alive 后台模块 / 页面隐藏时不建立 WS，避免多模块 WS 并发重连风暴
      if (!keepAliveActive || document.visibilityState !== 'visible') return;
      let token = getAccessToken();
      if (!token) { console.warn('[Screener WS] 无认证 token，跳过连接'); return; }
      // 💡 WS 层无 401 拦截器，需主动续期即将过期/已过期的 token（后端 TTL 仅 15 分钟）
      if (isTokenExpired(token)) {
        const refreshed = await refreshAccessToken();
        if (!refreshed) { console.warn('[Screener WS] Token 刷新失败，停止重连，请重新登录'); return; }
        token = refreshed;
      }
      // 💡 动态协议检测：HTTPS 页面必须使用 WSS
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      // ⚠️ 后端路由为 /api/v1/market/quotes/ws（main.py include_router prefix=/api/v1 + market_router prefix=/market）
      //    必须带 /api/v1 前缀，否则握手 404/失败
      try {
        wsRef.current = new WebSocket(`${wsProtocol}//${window.location.host}/api/v1/market/quotes/ws?token=${token}`);
      } catch (err) {
        console.error('[Screener WS] WebSocket 连接失败:', err);
        return;
      }
      wsRef.current.binaryType = "arraybuffer";
      wsRef.current.onopen = () => {
        if (!isMountedRef.current) return;
        wsOpenedRef.current = true;
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
      wsRef.current.onclose = (ev?: CloseEvent) => {
        wsOpenedRef.current = false;
        if (!isMountedRef.current) return;
        if (ev) console.warn(`[Screener WS] 连接关闭 code=${ev.code} reason=${ev.reason || '(空)'}`);
        // 💡 自愈：若关闭时 token 已过期（多半是后端 4002 鉴权拒绝），先刷新再重连；
        //    刷新失败则说明 Refresh Token 也失效，停止重连避免死循环，提示重新登录。
        const t = getAccessToken();
        if (t && isTokenExpired(t)) {
          refreshAccessToken().then((refreshed) => {
            if (!refreshed) { console.warn('[Screener WS] Token 刷新失败，停止重连，请重新登录'); return; }
            reconnectTimer = setTimeout(connectWS, 1000);
          });
          return;
        }
        reconnectTimer = setTimeout(connectWS, 1000);
      };
    };
    connectWS();
    const handleOnlineWS = () => { if (wsRef.current) wsRef.current.close(); };
    window.addEventListener('online', handleOnlineWS);
    // 💡 页面可见性 / keep-alive 激活态变化：隐藏或后台时断 WS，恢复时重连
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

  const handleAddSingle = (symbol: string) => { addTicker(symbol); toast({ title: '已加入自选池', description: `${formatDisplaySymbol(symbol)} 已成功推入 Watchlist。` }) }
  const handleAddBatch = () => { selected.forEach(addTicker); toast({ title: '批量操作成功', description: `已将 ${selected.length} 只标的加入自选池。` }) }
  const handleAddAndOpen = (symbol: string) => { addTicker(symbol); toast({ title: '正在前往图表...', description: `${formatDisplaySymbol(symbol)} 已推入自选池。` }); sessionStorage.setItem('quant_target_symbol', symbol); window.location.hash = 'quotes' }
  
  const handleSendToCopilot = useCallback((symbol: string) => {
    toast({ title: '🧠 正在召唤 Agent...', description: `即将对 ${formatDisplaySymbol(symbol)} 进行深度投研分析。` })
    const prompt = `请帮我生成一份针对【${symbol}】的深度体检研报。\n它是我刚刚通过量价筛选器捕获的高潜标的。请结合它当前的盘面特征，提取最新的财务基本面与近期新闻舆情，并给出风控建议。`
    window.dispatchEvent(new CustomEvent('quant_copilot_invoke', { detail: { prompt } }))
    window.location.hash = 'copilot'
  }, [toast])
  const handleSendToBacktest = useCallback((symbol: string) => {
    window.dispatchEvent(new CustomEvent('quant_strategy_invoke', { detail: { ticker: symbol } }))
    window.location.hash = 'strategy'
  }, [])
  const handleSubscribe = async () => {
    if (!dslQuery) return;
    const name = prompt('为这个选股策略起个名字吧：', nlpQuery.slice(0, 20) || '每日量化精选');
    if (!name) return;
    try {
      const res = await apiClient.post('/screener/subscribe', { name, dsl: dslQuery });
      if (res.data?.status === 'success') toast({ title: '🔔 订阅成功', description: res.data.message });
      else toast({ variant: 'destructive', title: '订阅失败', description: res.data?.message });
    } catch (e: any) { toast({ variant: 'destructive', title: '订阅异常', description: e.message || '无法连接到后端服务' }); }
  }

  const handleTranslate = async (overrideQuery?: string | any) => {
    const currentQuery = typeof overrideQuery === 'string' ? overrideQuery : nlpQuery;
    if (!currentQuery.trim()) return;
    if (typeof overrideQuery === 'string') setNlpQuery(currentQuery);
    setIsLoading(true); setProgress(5); setScanStatus('初始化 Agent...'); setDslQuery(''); setShowRawDsl(false); setResults([]);
    let finalDsl = '{"dsl_display": "market:us mktcap:>10B pe:10~50", "markets": ["US"], "exclude_st": false, "filters": [{"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 10000000000}, {"field": "PE_TTM", "type": "simple", "term": "TTM", "min_value": 10.0, "max_value": 50.0}]}';
    try {
      const transRes = await apiClient.post('/screener/translate', { query: currentQuery });
      if (transRes.data?.status === 'success' && transRes.data?.data) finalDsl = transRes.data.data;
    } catch (e: any) { /* ignore translate error */ }
    setDslQuery(finalDsl); setShowRawDsl(true); setProgress(10); setScanStatus('正在扫描...');
    const newItem = { nlp: currentQuery, dsl: finalDsl, time: Date.now() };
    const newHistory = [newItem, ...history.filter(item => item.nlp !== currentQuery)].slice(0, 20);
    localStorage.setItem('quant_screener_history', JSON.stringify(newHistory)); setHistory(newHistory);
    apiClient.post('/screener/history', { history: newHistory }).catch(() => {});
    try {
      const res = await apiClient.post('/screener/run', { dsl: finalDsl, page: 1, page_size: pageSize, sort_key: sortKey === 'rank' ? 'mktcap' : sortKey, sort_dir: sortDir, filters: columnFilters }, { timeout: 45000 });
      setProgress(100); setScanStatus('拉取完成，正在渲染...'); await new Promise(resolve => setTimeout(resolve, 400));
      if (res.data?.status === 'success' && res.data.data) {
        setResults(res.data.data); setTotalItems(res.data.total || res.data.data.length); setCurrentPage(1);
        try { localStorage.setItem('quant_screener_latest_state', JSON.stringify({ nlpQuery: currentQuery, dslQuery: finalDsl, results: res.data.data, totalItems: res.data.total || res.data.data.length })); } catch (e) { /* ignore storage error */ }
      } else {
        toast({ variant: 'destructive', title: '筛选失败', description: res.data?.message || '无法从后端获取筛选结果。' });
      }
    } catch (error: any) {
      setProgress(100); setScanStatus('请求中断'); await new Promise(resolve => setTimeout(resolve, 400));
      let errMsg = error.response?.data?.detail || error.message || '连接到筛选器服务时发生错误。';
      if (Array.isArray(errMsg)) errMsg = errMsg.map((e: any) => `${e.loc?.slice(1)?.join('.') || '参数'}: ${e.msg}`).join('\n');
      const descriptionContent = <span className="whitespace-pre-wrap leading-relaxed">{errMsg}</span>;
      toast({ variant: 'destructive', title: '请求异常', description: descriptionContent });
    } finally {
      setIsLoading(false); setTimeout(() => { setProgress(0); setScanStatus(''); }, 300); refreshPrompts();
    }
  };

  useEffect(() => {
    let timer: NodeJS.Timeout
    if (isLoading && progress > 0 && progress < 95) {
      timer = setInterval(() => {
        setProgress(p => {
          const next = p + Math.random() * 6 + 1
          if (next > 20 && next < 50) setScanStatus('解析 DSL 语义规则...')
          else if (next >= 50 && next < 75) setScanStatus('调度 Futu OpenD 接口...')
          else if (next >= 75 && next < 95) setScanStatus('全市场标的匹配过滤中...')
          return Math.min(95, next)
        })
      }, 150)
    }
    return () => clearInterval(timer)
  }, [isLoading, progress])

  const value = {
    nlpQuery, setNlpQuery, isLoading, setIsLoading, progress, setProgress, scanStatus, setScanStatus,
    dslQuery, setDslQuery, results, setResults, selected, setSelected, sortKey, setSortKey, sortDir, setSortDir,
    showSubManager, setShowSubManager, currentPage, setCurrentPage, pageSize, setPageSize, totalItems, setTotalItems,
    history, setHistory, showHistory, setShowHistory, placeholderText, setPlaceholderText, displayPrompts, setDisplayPrompts,
    showRawDsl, setShowRawDsl, showRagDict, setShowRagDict, previewData, setPreviewData, columnFilters, setColumnFilters,
    dynamicCols, paginatedData, realDataLength, totalPages, isAllCurrentPageSelected, pageSymbols,
    handleApplyFilter, handleClearFilter, refreshPrompts, fetchPageData, handleSort, toggleAll, toggleOne, handleExportCSV,
    handleAddSingle, handleAddBatch, handleAddAndOpen, handleSendToCopilot, handleSendToBacktest, handleSubscribe, handleTranslate
  };

  return <ScreenerContext.Provider value={value}>{children}</ScreenerContext.Provider>
}