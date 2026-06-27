import { useState, useEffect, useRef } from 'react'
import { TrendingUp, Loader2, Clock } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiClient, API_BASE_URL } from '@/lib/api-client'
import type { CapitalFlowItem } from '@/services/mock'
import { useSystemStore } from '@/stores/useSystemStore'
import { useToast } from '@/hooks/use-toast'
import { MarketClocks, AssetButton, playAlertSound } from '@/features/data-center/shared'
import { CapitalFlowPanel } from '@/features/data-center/capital-flow'
import { MarketSentimentPanel } from '@/features/data-center/market-sentiment'
import { MacroChartPanel } from '@/features/data-center/macro-chart'
import { MacroRiskRadar } from '@/features/data-center/macro-risk-radar'
import { EconomicCalendar } from '@/features/data-center/economic-calendar'
import { EarningsCalendar } from '@/features/data-center/earnings-calendar'
import { NewsStream } from '@/features/data-center/news-stream'
import { GlobalStyle } from '@/features/data-center/global-style'

export function DataCenterModule() {
  const setWsStatus = useSystemStore((state) => state.setWsStatus)
  const [m, setM] = useState(false); const [fetching, setFetching] = useState(false); const [last, setLast] = useState(''); const [radarInfo, setRadarInfo] = useState(false); const [calendarInfo, setCalendarInfo] = useState(false); const navigate = useNavigate();
  const [assets, setAssets] = useState<any[]>([]); const [radar, setRadar] = useState<any[]>([]); const [events, setEvents] = useState<any[]>([]); const [news, setNews] = useState<any[]>([])
  const [capitalFlows, setCapitalFlows] = useState<CapitalFlowItem[]>([])
  const [sentimentInd, setSentimentInd] = useState<any>(null)
  const [earnings, setEarnings] = useState<any[]>([])
  const [ecoMsg, setEcoMsg] = useState('')
  const [ecoDed, setEcoDed] = useState('')
  const [earnDed, setEarnDed] = useState('')
  const [visibleNewsCount, setVisibleNewsCount] = useState(5)
  const [selectedImpacts, setSelectedImpacts] = useState<string[]>(['high', 'medium', 'low'])
  const [selectedCountry, setSelectedCountry] = useState('all')
  const [selectedDateFilter, setSelectedDateFilter] = useState<'all' | 'today' | 'tomorrow'>('all')
  const [selectedEvent, setSelectedEvent] = useState<any>(null)
  const lastAlertedHeadline = useRef<string>('')
  const { toast } = useToast()

  useEffect(() => {
    setM(true)

    // 初始化时从 LocalStorage 恢复日历的筛选偏好
    const savedImpacts = localStorage.getItem('quant_macro_filter_impacts')
    if (savedImpacts !== null) {
      try { setSelectedImpacts(JSON.parse(savedImpacts)) } catch (e) {}
    } else {
      // 兼容旧的单一开关偏好设定
      const savedPref = localStorage.getItem('quant_macro_filter_high_impact')
      if (savedPref !== null) setSelectedImpacts(savedPref === 'true' ? ['high'] : ['high', 'medium', 'low'])
    }

    const savedCountry = localStorage.getItem('quant_macro_filter_country')
    if (savedCountry !== null) setSelectedCountry(savedCountry)

    const savedDateFilter = localStorage.getItem('quant_macro_filter_date')
    if (savedDateFilter) setSelectedDateFilter(savedDateFilter as any)

    let isMounted = true

    const fetchDashboardData = async () => {
      if (document.hidden) return
      try {
        setFetching(true)
        // 💡 优化：直接调用后端聚合好的大盘接口，同时包含日历、财报及大模型推演结果
        const [dashRes, flowRes, newsRes] = await Promise.allSettled([
          apiClient.get('/macro/dashboard'),
          apiClient.get('/macro/capital-flow'),
          apiClient.get('/macro/news?limit=50')
        ])

        if (!isMounted) return

        if (dashRes.status === 'fulfilled' && dashRes.value.data?.status === 'success') {
          const d = dashRes.value.data.data
          if (d.macroAssets) setAssets(d.macroAssets)
          if (d.radarData) setRadar(d.radarData)
          if (d.sentimentIndicators) setSentimentInd(d.sentimentIndicators)
          if (d.economicEvents) setEvents(d.economicEvents)
          if (d.earningsCalendar) setEarnings(d.earningsCalendar)

          setEcoMsg(d.economicEventsMessage || '')
          setEcoDed(d.economicEventsDeduction || '')
          setEarnDed(d.earningsCalendarDeduction || '')

          if (dashRes.value.data.updated_at) {
            setLast(new Date(dashRes.value.data.updated_at).toLocaleTimeString('zh-CN', { hour12: false }))
          }
        }
        if (flowRes.status === 'fulfilled' && flowRes.value.data?.status === 'success') {
          setCapitalFlows(flowRes.value.data.data || [])
        }
        if (newsRes.status === 'fulfilled' && newsRes.value.data?.status === 'success') {
          setNews(newsRes.value.data.data || [])
        }
      } catch (err) {
        console.warn('仪表盘数据获取失败:', err)
      } finally {
        if (isMounted) setFetching(false)
      }
    }

    fetchDashboardData()
    const intervalId = setInterval(fetchDashboardData, 300000)

    // 💡 断网与恢复重连监听机制
    const handleOnline = () => {
      const now = Date.now()
      if (!(window as any).__lastOnlineToast || now - (window as any).__lastOnlineToast > 2000) {
        toast({ title: '🌐 网络已恢复', description: '宏观数据中心已重新连接，正在同步...' })
        ;(window as any).__lastOnlineToast = now
      }
      fetchDashboardData() // 刷新大类资产与日历数据
    }
    const handleOffline = () => {
      const now = Date.now()
      if (!(window as any).__lastOfflineToast || now - (window as any).__lastOfflineToast > 2000) {
        toast({ variant: 'destructive', title: '🔌 网络连接断开', description: '当前处于离线状态，宏观数据更新已暂停。' })
        ;(window as any).__lastOfflineToast = now
      }
    }
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      isMounted = false
      clearInterval(intervalId)
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // 💡 添加手动单点刷新数据的函数 (通过 force_refresh 参数请求网关)
  const handleManualRefresh = async () => {
    try {
      // 增加 force_refresh 参数向后端声明绕过部分内存缓存
      const dashRes = await apiClient.get('/macro/dashboard?force_refresh=true')
      if (dashRes.data?.status === 'success') {
        const d = dashRes.data.data
        if (d.economicEvents) setEvents(d.economicEvents)
        if (d.earningsCalendar) setEarnings(d.earningsCalendar)
        if (dashRes.data.updated_at) {
          setLast(new Date(dashRes.data.updated_at).toLocaleTimeString('zh-CN', { hour12: false }))
        }
        toast({ title: '刷新成功', description: '已尝试获取最新发布数据' })
      }
    } catch (err) {
      console.warn('手动刷新失败:', err)
      toast({ variant: 'destructive', title: '刷新失败', description: '无法连接到数据网关' })
    }
  }

  // 当筛选偏好发生变化时，自动持久化到 LocalStorage
  useEffect(() => {
    if (m) {
      localStorage.setItem('quant_macro_filter_impacts', JSON.stringify(selectedImpacts))
      localStorage.setItem('quant_macro_filter_country', selectedCountry)
      localStorage.setItem('quant_macro_filter_date', selectedDateFilter)
    }
  }, [selectedImpacts, selectedCountry, selectedDateFilter, m])

  // 从事件数据中动态提取并排序国家列表
  const uniqueCountries = ['all', ...Array.from(new Set(events.map((ev: any) => ev.country)))].sort()

  // 挂载实时新闻流 WebSocket
  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimer: NodeJS.Timeout
    let isUnmounted = false

    const connect = () => {
      if (isUnmounted) return
      setWsStatus('CONNECTING')

      // 动态构建 WebSocket URL (安全替换 http 为 ws，适配环境变量)
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = API_BASE_URL.startsWith('http')
        ? API_BASE_URL.replace(/^http/, 'ws') + '/macro/news/ws'
        : `${protocol}//${window.location.host}${API_BASE_URL}/macro/news/ws`

      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        if (isUnmounted) return
        setWsStatus('CONNECTED')
      }
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'notification') {
            toast({
              title: msg.message.includes('🚨') ? '服务风控报警' : '系统恢复通知',
              description: msg.message,
              variant: msg.message.includes('🚨') ? 'destructive' : 'default',
            })
          } else if (msg.type === 'live_news' && msg.data) {
            // 定义需要触发警报的高危标签
            const highRiskTags = ['WAR', 'CRASH', 'GEOPOLITICS', 'EMERGENCY']
            const isHighRisk = msg.data.tags?.some((t: string) => highRiskTags.includes(t.toUpperCase()))

            setNews(prev => {
              // 基于新闻 headline 去重，防并发推两次
              if (prev.some(n => n.headline === msg.data.headline)) return prev

              // 触发高危提示音 (利用 ref 排重，并将副作用移出渲染核心栈)
              if (isHighRisk && lastAlertedHeadline.current !== msg.data.headline) {
                lastAlertedHeadline.current = msg.data.headline
                setTimeout(playAlertSound, 0)
              }

              // 自动将新新闻置顶，配合 React 渲染实现瀑布流下压
              return [msg.data, ...prev]
            })
          }
        } catch (err) {
          console.warn("News WS Error:", err)
        }
      }
    }

    // 延迟 1.5 秒连接，避免与首次全量渲染争抢主线程卡顿
    const t = setTimeout(connect, 1500)

    // 💡 断网恢复时主动重连 WebSocket
    const handleOnlineWS = () => {
      if (ws) ws.close()
      setTimeout(() => { if (!isUnmounted) connect() }, 500)
    }
    window.addEventListener('online', handleOnlineWS)

    return () => {
      clearTimeout(t); isUnmounted = true
      window.removeEventListener('online', handleOnlineWS); ws?.close()
    }
  }, [])

  if (!m) return null
  return (<div className="space-y-2.5">
    {/* Title */}
    <div className="flex items-center gap-2"><div className="h-1.5 w-1.5 rounded-full bg-sky-500 dark:bg-sky-400" /><h1 className="text-base font-bold tracking-tight">数据中心与宏观</h1><span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">Macro Intelligence</span>{fetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground ml-2" />}{last && <div className="ml-auto flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground bg-secondary/50 border border-border/30 px-2 py-1 rounded"><Clock className="h-3 w-3" /><span>{last}</span></div>}</div>
    {/* 资金流 */}
    <CapitalFlowPanel data={capitalFlows} />
    {/* 大类资产 + 情绪风向标 + 雷达 */}
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px_240px] xl:grid-cols-[1fr_240px_260px] gap-2.5">
      <div className="glass-card rounded-lg overflow-hidden"><div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2"><TrendingUp className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">大类资产走势</span><MarketClocks /></div><div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-6 gap-2 p-2 bg-slate-50/50 dark:bg-black/10">{assets.filter((a: any) => a.symbol !== 'VIX').map((a: any) => (<AssetButton key={a.symbol} asset={a} />))}</div></div>
      <MarketSentimentPanel vixData={assets.find((a: any) => a.symbol === 'VIX')} sentimentInd={sentimentInd} />
      <MacroRiskRadar radar={radar} radarInfo={radarInfo} setRadarInfo={setRadarInfo} />
    </div>
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
      {/* 经济日历 */}
      <EconomicCalendar
        events={events}
        calendarInfo={calendarInfo}
        setCalendarInfo={setCalendarInfo}
        selectedEvent={selectedEvent}
        setSelectedEvent={setSelectedEvent}
        selectedDateFilter={selectedDateFilter}
        setSelectedDateFilter={setSelectedDateFilter}
        selectedCountry={selectedCountry}
        setSelectedCountry={setSelectedCountry}
        selectedImpacts={selectedImpacts}
        setSelectedImpacts={setSelectedImpacts}
        uniqueCountries={uniqueCountries}
        ecoMsg={ecoMsg}
        ecoDed={ecoDed}
        handleManualRefresh={handleManualRefresh}
      />
      {/* 财报日历 */}
      <EarningsCalendar earnings={earnings} earnDed={earnDed} handleManualRefresh={handleManualRefresh} />
      {/* 新闻情绪 */}
      <NewsStream news={news} visibleNewsCount={visibleNewsCount} setVisibleNewsCount={setVisibleNewsCount} />
      {/* FRED 宏观图表查询 */}
      <div className="col-span-1">
        <MacroChartPanel />
      </div>
    </div>
    {/* 全局动画与自定义滚动条样式 */}
    <GlobalStyle />
  </div>)
}
