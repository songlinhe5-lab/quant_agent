import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient, getValidAccessToken, getWsBaseUrl } from '@/lib/api-client'
import type { CapitalFlowItem } from '@/services/mock'
import { useSystemStore } from '@/stores/useSystemStore'
import { useToast } from '@/hooks/use-toast'
import { useKeepAliveActive } from '@/components/layout/keep-alive-context'
import { playAlertSound } from '@/features/data-center/shared'
import type { MarginMarketData } from '@/features/data-center/margin-trading'
import type { SectorFundFlowData } from '@/features/data-center/sector-flow'

export type HubTab = 'overview' | 'capital' | 'calendars' | 'watchlist'

export function useDashboardData() {
  const setWsStatus = useSystemStore((state) => state.setWsStatus)
  const keepAliveActive = useKeepAliveActive()
  const { toast } = useToast()
  const _navigate = useNavigate()

  const [fetching, setFetching] = useState(false)
  const [last, setLast] = useState('')
  const [radarInfo, setRadarInfo] = useState(false)
  const [calendarInfo, setCalendarInfo] = useState(false)

  const [assets, setAssets] = useState<any[]>([])
  const [radar, setRadar] = useState<any[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [news, setNews] = useState<any[]>([])
  const [capitalFlows, setCapitalFlows] = useState<CapitalFlowItem[]>([])
  const [sentimentInd, setSentimentInd] = useState<any>(null)
  const [earnings, setEarnings] = useState<any[]>([])
  const [earningsStatus, setEarningsStatus] = useState<string>('unknown')
  const [earningsMessage, setEarningsMessage] = useState<string>('')
  const [marginData, setMarginData] = useState<MarginMarketData[]>([])
  const [marginStatus, setMarginStatus] = useState<string>('unknown')
  const [sectorFlowData, setSectorFlowData] = useState<SectorFundFlowData | null>(null)
  const [sectorFlowStatus, setSectorFlowStatus] = useState<string>('unknown')
  const [ecoMsg, setEcoMsg] = useState('')
  const [ecoDed, setEcoDed] = useState('')
  const [ecoSources, setEcoSources] = useState<string[]>([])
  const [earnDed, setEarnDed] = useState('')

  // 日历筛选偏好（localStorage 持久化，跨子组件共享）
  const [m, setM] = useState(false)
  const [selectedImpacts, setSelectedImpacts] = useState<string[]>(['high', 'medium', 'low'])
  const [selectedCountry, setSelectedCountry] = useState('all')
  const [selectedDateFilter, setSelectedDateFilter] = useState<'past' | 'all' | 'today' | 'tomorrow'>('all')
  const [selectedEvent, setSelectedEvent] = useState<any>(null)
  const [visibleNewsCount, setVisibleNewsCount] = useState(5)
  const lastAlertedHeadline = useRef<string>('')

  useEffect(() => {
    setM(true)
    const savedImpacts = localStorage.getItem('quant_macro_filter_impacts')
    if (savedImpacts !== null) {
      try { setSelectedImpacts(JSON.parse(savedImpacts)) } catch (_e) { /* ignore */ }
    } else {
      const savedPref = localStorage.getItem('quant_macro_filter_high_impact')
      if (savedPref !== null) setSelectedImpacts(savedPref === 'true' ? ['high'] : ['high', 'medium', 'low'])
    }
    const savedCountry = localStorage.getItem('quant_macro_filter_country')
    if (savedCountry !== null) setSelectedCountry(savedCountry)
    const savedDateFilter = localStorage.getItem('quant_macro_filter_date')
    if (savedDateFilter) setSelectedDateFilter(savedDateFilter as any)
  }, [])

  const fetchDashboardData = useCallback(async () => {
    if (document.hidden) return
    try {
      setFetching(true)
      const [dashRes, flowRes, newsRes] = await Promise.allSettled([
        apiClient.get('/macro/dashboard'),
        apiClient.get('/macro/capital-flow'),
        apiClient.get('/macro/news?limit=50'),
      ])
      if (dashRes.status === 'fulfilled' && dashRes.value.data?.status === 'success') {
        const d = dashRes.value.data.data
        if (d.macroAssets) setAssets(d.macroAssets)
        if (d.radarData) setRadar(d.radarData)
        if (d.sentimentIndicators) setSentimentInd(d.sentimentIndicators)
        if (d.economicEvents) setEvents(d.economicEvents)
        if (d.earningsCalendar) setEarnings(d.earningsCalendar)
        if (d.earningsStatus) setEarningsStatus(d.earningsStatus)
        if (d.earningsMessage) setEarningsMessage(d.earningsMessage)
        if (d.marginTrading) setMarginData(d.marginTrading)
        if (d.marginTradingStatus) setMarginStatus(d.marginTradingStatus)
        if (d.sectorFundFlow) setSectorFlowData(d.sectorFundFlow)
        if (d.sectorFundFlowStatus) setSectorFlowStatus(d.sectorFundFlowStatus)
        setEcoMsg(d.economicEventsMessage || '')
        setEcoDed(d.economicEventsDeduction || '')
        setEcoSources(d.economicEventsSources || [])
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
      setFetching(false)
    }
  }, [])

  const handleManualRefresh = useCallback(async () => {
    try {
      const dashRes = await apiClient.get('/macro/dashboard?force_refresh=true')
      if (dashRes.data?.status === 'success') {
        const d = dashRes.data.data
        if (d.economicEvents) setEvents(d.economicEvents)
        if (d.economicEventsSources) setEcoSources(d.economicEventsSources)
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
  }, [toast])

  // 日历筛选持久化
  useEffect(() => {
    if (m) {
      localStorage.setItem('quant_macro_filter_impacts', JSON.stringify(selectedImpacts))
      localStorage.setItem('quant_macro_filter_country', selectedCountry)
      localStorage.setItem('quant_macro_filter_date', selectedDateFilter)
    }
  }, [selectedImpacts, selectedCountry, selectedDateFilter, m])

  const uniqueCountries = useMemo(
    () => ['all', ...Array.from(new Set(events.map((ev: any) => ev.country)))].sort(),
    [events],
  )

  const shortSellingHasContent = useMemo(() => {
    const valid = (n: any) => n != null && !Number.isNaN(n)
    const marketHasContent = (mk: any) =>
      valid(mk.financing_balance) || valid(mk.securities_balance) ||
      valid(mk.short_sale_volume) || valid(mk.short_volume_ratio) ||
      valid(mk.short_interest_shares) || valid(mk.short_interest_ratio)
    return (marginData || []).some(marketHasContent)
  }, [marginData])

  const sentimentHasContent = useMemo(() => {
    const vixOk = !!assets.find((a: any) => a.symbol === 'VIX')
    const sentOk = !!sentimentInd && Object.keys(sentimentInd).length > 0
    const radarOk = (radar?.length ?? 0) > 0
    return vixOk || sentOk || radarOk
  }, [assets, sentimentInd, radar])

  // 首次加载 + 5 分钟轮询 + 断网恢复
  useEffect(() => {
    fetchDashboardData()
    const intervalId = setInterval(fetchDashboardData, 300000)
    const handleOnline = () => {
      const now = Date.now()
      if (!(window as any).__lastOnlineToast || now - (window as any).__lastOnlineToast > 2000) {
        toast({ title: '🌐 网络已恢复', description: '宏观数据中心已重新连接，正在同步...' })
        ;(window as any).__lastOnlineToast = now
      }
      fetchDashboardData()
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
      clearInterval(intervalId)
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [fetchDashboardData, toast])

  // 实时新闻流 WS
  useEffect(() => {
    let ws: WebSocket | null = null
    let isUnmounted = false
    const connect = async () => {
      if (isUnmounted) return
      if (!keepAliveActive || document.visibilityState !== 'visible') return
      setWsStatus('CONNECTING')
      const token = await getValidAccessToken()
      const wsUrl = `${getWsBaseUrl()}/macro/news/ws` + (token ? `?token=${token}` : '')
      ws = new WebSocket(wsUrl)
      ws.onopen = () => { if (!isUnmounted) setWsStatus('CONNECTED') }
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
            const highRiskTags = ['WAR', 'CRASH', 'GEOPOLITICS', 'EMERGENCY']
            const isHighRisk = msg.data.tags?.some((t: string) => highRiskTags.includes(t.toUpperCase()))
            setNews((prev) => {
              if (prev.some((n: any) => n.headline === msg.data.headline)) return prev
              if (isHighRisk && lastAlertedHeadline.current !== msg.data.headline) {
                lastAlertedHeadline.current = msg.data.headline
                setTimeout(playAlertSound, 0)
              }
              return [msg.data, ...prev]
            })
          }
        } catch (err) {
          console.warn('News WS Error:', err)
        }
      }
    }
    const t = setTimeout(connect, 1500)
    const handleOnlineWS = () => {
      if (!keepAliveActive || document.visibilityState !== 'visible') return
      if (ws) ws.close()
      setTimeout(() => { if (!isUnmounted) connect() }, 500)
    }
    const handleVisibilityOrActive = () => {
      if (isUnmounted) return
      if (!keepAliveActive || document.visibilityState !== 'visible') {
        if (ws) { ws.onclose = null; ws.close(); ws = null }
      } else {
        connect()
      }
    }
    window.addEventListener('online', handleOnlineWS)
    document.addEventListener('visibilitychange', handleVisibilityOrActive)
    return () => {
      clearTimeout(t); isUnmounted = true
      window.removeEventListener('online', handleOnlineWS)
      document.removeEventListener('visibilitychange', handleVisibilityOrActive)
      ws?.close()
    }
  }, [keepAliveActive, setWsStatus, toast])

  return {
    // state
    fetching, last, radarInfo, setRadarInfo, calendarInfo, setCalendarInfo,
    assets, radar, events, news, capitalFlows, sentimentInd, earnings,
    earningsStatus, earningsMessage, marginData, marginStatus, sectorFlowData,
    sectorFlowStatus, ecoMsg, ecoDed, ecoSources, earnDed,
    selectedImpacts, setSelectedImpacts, selectedCountry, setSelectedCountry,
    selectedDateFilter, setSelectedDateFilter, selectedEvent, setSelectedEvent,
    visibleNewsCount, setVisibleNewsCount, uniqueCountries,
    shortSellingHasContent, sentimentHasContent,
    // actions
    handleManualRefresh,
  }
}
