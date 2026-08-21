import React, { useState, useEffect, useRef, useCallback } from 'react'
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries, HistogramSeries, AreaSeries, BaselineSeries, LineStyle, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp, type IPriceLine, type ISeriesMarkersPluginApi, type SeriesMarker, type Time } from 'lightweight-charts'
import { AlertTriangle, TrendingUp, TrendingDown, Eye, EyeOff, Pencil, Globe, ChevronRight, Minus, Square, Spline, Eraser, MousePointerClick, Sigma, Bell } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { crosshairSync } from './chart-crosshair-sync'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api-client'
import { useIndicatorWorker } from '@/hooks/use-indicator-worker'
import { HighFreqChartWrapper } from '@/features/quotes/high-freq-chart-wrapper'
import type { WatchlistItem } from '@/stores/use-watchlist'
import { useCopilotContextStore } from '@/stores/useCopilotContextStore'
import { useChartAnnotationStore } from '@/stores/useChartAnnotationStore'
import { usePatternStore } from '@/stores/usePatternStore'
import type { ChartAnnotationPayload } from '@/features/copilot/types'
import { useTradeStore, type OrderSide } from '@/stores/useTradeStore'
import { OrderConfirmModal } from './order-confirm-modal'
import { evaluate, suggestPane, type CIBar } from './custom-indicator/engine'
import { useCustomIndicatorStore } from './custom-indicator/store'
import { CustomIndicatorPanel } from './custom-indicator/panel'
import { AlertSandboxPanel } from './custom-indicator/alert-sandbox-panel'
import { SEMANTIC_COLORS, MARKET_COLORS } from '@/lib/constants'

// 💡 个股事件类型定义
interface StockEvent {
  date: string
  type: 'earnings' | 'dividend' | 'news'
  label: string
  impact: 'high' | 'medium' | 'low'
  data?: {
    epsEstimate?: number
    epsActual?: number
    source?: string
    url?: string
  }
}

// 💡 图表周期配置：分时图、Tick图、5日图、日K图，后续可扩展周K/月K/季K/年K
const periods = [
  { id: '1m', label: '分时' },
  { id: 'tick', label: 'Tick' },
  { id: '5m', label: '5日' },
  { id: '1d', label: '日K' },
  { id: '1w', label: '周K' },
  { id: '1M', label: '月K' },
]

class TrendLineRenderer {
  _p1: any; _p2: any; _color: string;
  constructor(p1: any, p2: any, color: string) { this._p1 = p1; this._p2 = p2; this._color = color; }
  draw(target: any) {
    if (!this._p1 || !this._p2) return;
    if (target.useMediaCoordinateSpace) {
      target.useMediaCoordinateSpace(({ context: ctx }: any) => {
        ctx.beginPath(); ctx.moveTo(this._p1.x, this._p1.y); ctx.lineTo(this._p2.x, this._p2.y); ctx.strokeStyle = this._color; ctx.lineWidth = 2; ctx.stroke();
      });
    } else {
      const ctx = target.context || target;
      ctx.beginPath(); ctx.moveTo(this._p1.x, this._p1.y); ctx.lineTo(this._p2.x, this._p2.y); ctx.strokeStyle = this._color; ctx.lineWidth = 2; ctx.stroke();
    }
  }
}
class TrendLinePaneView {
  _source: any; _p1: any = null; _p2: any = null;
  constructor(source: any) { this._source = source; }
  update() {
    const s = this._source;
    if (!s.series || !s.chart || !s.t1 || !s.p1 || !s.t2 || !s.p2) return;
    const x1 = s.chart.timeScale().timeToCoordinate(s.t1); const y1 = s.series.priceToCoordinate(s.p1);
    const x2 = s.chart.timeScale().timeToCoordinate(s.t2); const y2 = s.series.priceToCoordinate(s.p2);
    if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) { this._p1 = { x: x1, y: y1 }; this._p2 = { x: x2, y: y2 }; }
  }
  renderer() { return new TrendLineRenderer(this._p1, this._p2, this._source.color); }
}
class TrendLinePrimitive {
  chart: any; series: any; t1: any; p1: any; t2: any; p2: any; color: string; _paneViews: any[]; _requestUpdate: () => void = () => {};
  constructor(chart: any, series: any, t1: any, p1: any, color: string) {
    this.chart = chart; this.series = series; this.t1 = t1; this.p1 = p1; this.t2 = t1; this.p2 = p1; this.color = color;
    this._paneViews = [new TrendLinePaneView(this)];
  }
  updateAllViews() { this._paneViews.forEach(v => v.update()); }
  paneViews() { return this._paneViews; }
  attached({ requestUpdate }: any) { this._requestUpdate = requestUpdate; }
  detached() {}
  updateEndPoint(t: any, p: any) { this.t2 = t; this.p2 = p; this._requestUpdate(); }
}

// PROD-03: 画线工具扩展（水平线 / 矩形 / 斐波那契回撤），与趋势线共用 lightweight-charts v5 IPrimitive 接口
type DrawTool = 'none' | 'trendline' | 'hline' | 'fib' | 'rect'

class HLinePaneView {
  _source: any; _y: number | null = null;
  constructor(s: any) { this._source = s; }
  update() { this._y = this._source.series.priceToCoordinate(this._source.p); }
  renderer() {
    const y = this._y; const source = this._source;
    return { draw: (target: any) => { target.useMediaCoordinateSpace(({ context: ctx, mediaSize }: any) => {
      if (y == null) return;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(mediaSize.width, y);
      ctx.strokeStyle = source.color; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = source.color; ctx.font = '10px ui-monospace, monospace';
      ctx.fillText(source.p.toFixed(2), 6, y - 4);
    }); } };
  }
}
class HLinePrimitive {
  series: any; t: any; p: any; color: string; _paneViews: any[]; _requestUpdate: () => void = () => {};
  constructor(series: any, t: any, p: any, color: string) { this.series = series; this.t = t; this.p = p; this.color = color; this._paneViews = [new HLinePaneView(this)]; }
  updateAllViews() { this._paneViews.forEach(v => v.update()); }
  paneViews() { return this._paneViews; }
  attached({ requestUpdate }: any) { this._requestUpdate = requestUpdate; }
  detached() {}
}

class RectanglePaneView {
  _source: any; _x1: number | null = null; _y1: number | null = null; _x2: number | null = null; _y2: number | null = null;
  constructor(s: any) { this._source = s; }
  update() {
    const s = this._source;
    this._x1 = s.chart.timeScale().timeToCoordinate(s.t1);
    this._x2 = s.chart.timeScale().timeToCoordinate(s.t2);
    this._y1 = s.series.priceToCoordinate(s.p1);
    this._y2 = s.series.priceToCoordinate(s.p2);
  }
  renderer() {
    const x1 = this._x1, x2 = this._x2, y1 = this._y1, y2 = this._y2, source = this._source;
    return { draw: (target: any) => { target.useMediaCoordinateSpace(({ context: ctx }: any) => {
      if (x1 == null || x2 == null || y1 == null || y2 == null) return;
      const x = Math.min(x1, x2), yy = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
      ctx.fillStyle = source.color; ctx.globalAlpha = 0.08; ctx.fillRect(x, yy, w, h); ctx.globalAlpha = 1;
      ctx.strokeStyle = source.color; ctx.lineWidth = 1.5; ctx.strokeRect(x, yy, w, h);
    }); } };
  }
}
class RectanglePrimitive {
  chart: any; series: any; t1: any; p1: any; t2: any; p2: any; color: string; _paneViews: any[]; _requestUpdate: () => void = () => {};
  constructor(chart: any, series: any, t: any, p: any, color: string) { this.chart = chart; this.series = series; this.t1 = t; this.p1 = p; this.t2 = t; this.p2 = p; this.color = color; this._paneViews = [new RectanglePaneView(this)]; }
  updateAllViews() { this._paneViews.forEach(v => v.update()); }
  paneViews() { return this._paneViews; }
  attached({ requestUpdate }: any) { this._requestUpdate = requestUpdate; }
  detached() {}
  updateEndPoint(t: any, p: any) { this.t2 = t; this.p2 = p; this._requestUpdate(); }
}

class FibPaneView {
  _source: any; _y1: number | null = null; _y2: number | null = null;
  constructor(s: any) { this._source = s; }
  update() { const s = this._source; this._y1 = s.series.priceToCoordinate(s.p1); this._y2 = s.series.priceToCoordinate(s.p2); }
  renderer() {
    const y1 = this._y1, y2 = this._y2, source = this._source;
    const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
    return { draw: (target: any) => { target.useMediaCoordinateSpace(({ context: ctx, mediaSize }: any) => {
      if (y1 == null || y2 == null) return;
      ctx.font = '10px ui-monospace, monospace';
      ctx.fillStyle = source.color; ctx.globalAlpha = 0.06; ctx.fillRect(0, Math.min(y1, y2), mediaSize.width, Math.abs(y2 - y1)); ctx.globalAlpha = 1;
      levels.forEach((lvl: number) => {
        const y = y1 + (y2 - y1) * lvl; const price = source.p1 + (source.p2 - source.p1) * lvl;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(mediaSize.width, y);
        ctx.strokeStyle = source.color; ctx.globalAlpha = 0.5; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
        ctx.fillStyle = source.color; ctx.fillText(`${(lvl * 100).toFixed(1)}%  ${price.toFixed(2)}`, 6, y - 3);
      });
    }); } };
  }
}
class FibRetracementPrimitive {
  series: any; t1: any; p1: any; t2: any; p2: any; color: string; _paneViews: any[]; _requestUpdate: () => void = () => {};
  constructor(series: any, t: any, p: any, color: string) { this.series = series; this.t1 = t; this.p1 = p; this.t2 = t; this.p2 = p; this.color = color; this._paneViews = [new FibPaneView(this)]; }
  updateAllViews() { this._paneViews.forEach(v => v.update()); }
  paneViews() { return this._paneViews; }
  attached({ requestUpdate }: any) { this._requestUpdate = requestUpdate; }
  detached() {}
  updateEndPoint(t: any, p: any) { this.t2 = t; this.p2 = p; this._requestUpdate(); }
}

const DRAW_TOOLS: { id: DrawTool; label: string; icon: any }[] = [
  { id: 'trendline', label: '趋势线（两点连线）', icon: Pencil },
  { id: 'hline', label: '水平线（单击定位价位）', icon: Minus },
  { id: 'fib', label: '斐波那契回撤（两点）', icon: Spline },
  { id: 'rect', label: '矩形区域（两点）', icon: Square },
]

interface LightweightChartCanvasProps {
  selectedSymbol: string;
  selectedPeriod: string;
  setSelectedPeriod: (p: string) => void;
  theme?: string;
  realQuote: any;
  realHistory: any[];
  gatewayStatus: string;
  isWatchlistExpanded: boolean;
  toggleWatchlist: () => void;
  selectedItem: WatchlistItem;
  hasData: boolean;
  syncGroup?: string;
}

export function LightweightChartCanvas({ selectedSymbol, selectedPeriod, setSelectedPeriod, theme, realQuote, realHistory, gatewayStatus, isWatchlistExpanded, toggleWatchlist, selectedItem, hasData, syncGroup = 'default' }: LightweightChartCanvasProps) {
  const { toast } = useToast()
  const [showEvents, setShowEvents] = useState(true)
  const [showMA20, setShowMA20] = useState(true)
  const [showMA50, setShowMA50] = useState(true)
  const [showMA200, setShowMA200] = useState(true)
  const [showBB, setShowBB] = useState(true)
  const [showMACD, setShowMACD] = useState(true)
  const [showRSI, setShowRSI] = useState(true)
  const [showKDJ, setShowKDJ] = useState(true)
  const [drawTool, setDrawTool] = useState<DrawTool>('none')
  const isDrawModeRef = useRef(false)
  useEffect(() => { isDrawModeRef.current = drawTool !== 'none' }, [drawTool])
  const drawToolRef = useRef<DrawTool>('none')
  useEffect(() => { drawToolRef.current = drawTool }, [drawTool])
  const drawingsRef = useRef<any[]>([])
  const clearDrawings = useCallback(() => {
    const s = seriesRef.current
    if (s) {
      drawingsRef.current.forEach((p: any) => { try { s.detachPrimitive(p) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ } })
      const c = chartContainerRef.current as any
      if (c && c._activeDrawingPlugin) { try { s.detachPrimitive(c._activeDrawingPlugin) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ }; c._activeDrawingPlugin = null }
    }
    drawingsRef.current = []
  }, [])
  const selectTool = (id: DrawTool) => {
    const next = drawTool === id ? 'none' : id
    if (next === 'none' && drawTool !== 'none') {
      const c = chartContainerRef.current as any
      if (c && c._activeDrawingPlugin) { try { seriesRef.current?.detachPrimitive(c._activeDrawingPlugin) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ }; c._activeDrawingPlugin = null }
    }
    if (next !== 'none') setOrderMode(false)
    setDrawTool(next)
  }

  // PROD-09: 图表内拖拽式下单（沙箱推演）状态与价格线渲染
  const [orderMode, setOrderMode] = useState(false)
  const orderModeRef = useRef(false)
  useEffect(() => { orderModeRef.current = orderMode }, [orderMode])
  const positionCount = useTradeStore((s) => (s.positions[selectedSymbol] ?? []).length)

  // PROD-11: 自定义指标脚本（Pine Script 简化版）面板与渲染引用
  const [showCIPanel, setShowCIPanel] = useState(false)
  const [showAlertSandbox, setShowAlertSandbox] = useState(false)
  const customMarkersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const customLineRefs = useRef<Record<string, ISeriesApi<'Line'>>>({})
  const currentBarsRef = useRef<CIBar[]>([])
  // 记录每个布尔指标已登记的「末根上穿」触发日，避免重复推入信号日志
  const ciSignalStateRef = useRef<Record<string, string>>({})
  // Toast 武装标记：延迟 2s，避免首屏 K 线加载时的历史信号轰炸，仅实时新信号提醒
  const ciToastArmedRef = useRef(false)
  // 系统通知权限仅请求一次，避免重复弹窗
  const ciNotifAskedRef = useRef(false)
  useEffect(() => {
    const timer = setTimeout(() => { ciToastArmedRef.current = true }, 2000)
    return () => clearTimeout(timer)
  }, [])

  const applyCustomIndicators = useCallback((bars: CIBar[]) => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series || bars.length === 0) return
    // 清理上一次叠加的自定义数值线
    Object.values(customLineRefs.current).forEach((s) => { try { chart.removeSeries(s) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ } })
    customLineRefs.current = {}
    const markers: SeriesMarker<Time>[] = []
    const list = useCustomIndicatorStore.getState().indicators.filter((i) => i.visible)
    for (const ind of list) {
      const r = evaluate(ind.expr, bars, ind.params)
      if (!r.ok) continue
      if (r.isBool) {
        for (let i = 0; i < r.values.length; i++) {
          if (r.values[i] === 1) {
            const t = (new Date(bars[i].time.replace(/-/g, '/')).getTime() / 1000) as UTCTimestamp
            markers.push({ time: t, position: 'aboveBar', color: ind.color, shape: 'circle', text: ind.name })
          }
        }
        // 末根 K 线上穿（0->1 跳变）记入信号日志，供提醒/回测消费
        let lastFlip = -1
        for (let i = 1; i < r.values.length; i++) {
          if (r.values[i] === 1 && r.values[i - 1] !== 1) lastFlip = i
        }
        if (lastFlip === r.values.length - 1) {
          const t = bars[lastFlip].time
          if (ciSignalStateRef.current[ind.id] !== t) {
            ciSignalStateRef.current[ind.id] = t
            useCustomIndicatorStore.getState().pushSignal({ indId: ind.id, indName: ind.name, expr: ind.expr, time: t, ts: Date.now() })
            if (ciToastArmedRef.current) {
              const title = `📡 信号触发 · ${ind.name}`
              const body = `${t} 满足：${ind.expr}`
              toast({ title, description: body })
              // 系统级通知：跨标签页 / 后台运行时仍可见
              if (typeof Notification !== 'undefined') {
                if (Notification.permission === 'granted') {
                  new Notification(title, { body })
                } else if (Notification.permission === 'default' && !ciNotifAskedRef.current) {
                  ciNotifAskedRef.current = true
                  Notification.requestPermission().catch(() => {})
                }
              }
            }
          }
        }
      } else {
        const pane = ind.pane ?? suggestPane(ind.expr)
        const psId = pane === 'separate' ? 'ci-separate' : 'right'
        const line = chart.addSeries(LineSeries, {
          color: ind.color, lineWidth: 1,
          priceScaleId: psId,
          crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
        })
        if (pane === 'separate') {
          chart.priceScale(psId).applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
        }
        const data: { time: UTCTimestamp; value: number }[] = []
        for (let i = 0; i < r.values.length; i++) {
          const v = r.values[i]
          if (v == null) continue
          data.push({ time: (new Date(bars[i].time.replace(/-/g, '/')).getTime() / 1000) as UTCTimestamp, value: v })
        }
        line.setData(data)
        customLineRefs.current[ind.id] = line
      }
    }
    if (markers.length) {
      if (!customMarkersApiRef.current) customMarkersApiRef.current = createSeriesMarkers(series, markers)
      else customMarkersApiRef.current.setMarkers(markers)
    } else if (customMarkersApiRef.current) {
      customMarkersApiRef.current.setMarkers([])
    }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const applyCIPanelRef = useRef(applyCustomIndicators)
  applyCIPanelRef.current = applyCustomIndicators
  const orderPreviewLineRef = useRef<IPriceLine | null>(null)
  const positionLinesRef = useRef<Record<string, IPriceLine>>({})

  const clearPositionLines = useCallback(() => {
    if (!seriesRef.current) return
    Object.values(positionLinesRef.current).forEach((pl) => { try { seriesRef.current?.removePriceLine(pl) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ } })
    positionLinesRef.current = {}
  }, [])

  const applyPositionLines = useCallback(() => {
    const series = seriesRef.current
    if (!series) return
    clearPositionLines()
    const positions = useTradeStore.getState().positions[selectedSymbol] ?? []
    positions.forEach((pos) => {
      positionLinesRef.current[`${pos.id}:entry`] = series.createPriceLine({ price: pos.entryPrice, color: pos.side === 'BUY' ? '#10b981' : '#ef4444', lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: `${pos.side} ${pos.qty}` })
      if (pos.sl != null) positionLinesRef.current[`${pos.id}:sl`] = series.createPriceLine({ price: pos.sl, color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'SL' })
      if (pos.tp != null) positionLinesRef.current[`${pos.id}:tp`] = series.createPriceLine({ price: pos.tp, color: '#10b981', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'TP' })
    })
  }, [selectedSymbol, clearPositionLines])

  // PROD-01: 将 K线 上下文（标的 + 周期 + 技术指标）写入 AI 副驾
  useEffect(() => {
    if (!selectedSymbol) {
      useCopilotContextStore.getState().clearContext()
      return
    }
    const active: string[] = []
    if (showMA20) active.push('MA20')
    if (showMA50) active.push('MA50')
    if (showMA200) active.push('MA200')
    if (showBB) active.push('BB')
    if (showMACD) active.push('MACD')
    if (showRSI) active.push('RSI')
    if (showKDJ) active.push('KDJ')
    useCopilotContextStore.getState().setContext({
      kind: 'kline',
      title: 'K线',
      symbol: selectedSymbol,
      summary: `标的: ${selectedSymbol}\n周期: ${selectedPeriod}\n技术指标: ${active.join(', ') || '无'}`,
    })
  }, [selectedSymbol, selectedPeriod, showMA20, showMA50, showMA200, showBB, showMACD, showRSI, showKDJ])

  // 💡 个股事件状态（从后端获取）
  const [stockEvents, setStockEvents] = useState<StockEvent[]>([])

  // 💡 获取个股相关事件（财报、分红、重大新闻）
  useEffect(() => {
    let isMounted = true

    async function fetchStockEvents() {
      if (!selectedSymbol) return

      try {
        const sym = selectedSymbol.replace('/', '')
        const res = await apiClient.get(`/market/events/${sym}`, { days_back: 30, days_ahead: 30 })
        // BE-13 方案 B: /events 返回扁平 payload {ticker,count,data,degraded}
        // 经中间件包信封 + apiClient 解包后, res.data 即该 payload, 直接读 .data
        if (isMounted && res.data?.data) {
          setStockEvents(res.data.data)
        }
      } catch (e) {
        console.error('Failed to fetch stock events:', e)
      }
    }

    fetchStockEvents()

    return () => { isMounted = false }
  }, [selectedSymbol])

  // PROD-12: 跨图表十字线同步所需的稳定实例 id 与防回环标记
  const chartIdRef = useRef<string>(`chart-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`)
  const isExternalSyncRef = useRef<boolean>(false)

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const ma20Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ma50Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ma200Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const bbUpperRef = useRef<ISeriesApi<'Area'> | null>(null)
  const bbLowerRef = useRef<ISeriesApi<'Line'> | null>(null)
  const macdDiffRef = useRef<ISeriesApi<'Line'> | null>(null)
  const macdDeaRef = useRef<ISeriesApi<'Line'> | null>(null)
  const macdHistRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const rsiLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const rsiHistRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const kdjKRef = useRef<ISeriesApi<'Line'> | null>(null)
  const kdjDRef = useRef<ISeriesApi<'Line'> | null>(null)
  const kdjJRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const currentPriceLineRef = useRef<IPriceLine | null>(null)
  const lastCandleRef = useRef<any>(null)
  const dataLengthRef = useRef<number>(0)
  const isFirstLoadFittedRef = useRef(false)
  const markersRef = useRef<any[]>([])
  // PROD-02: AI 图表标注渲染相关引用
  const aiMarkersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const aiPriceLinesRef = useRef<IPriceLine[]>([])
  const aiZoneSeriesRef = useRef<ISeriesApi<'Baseline'>[]>([])
  const aiSignalsClickRef = useRef<{ time: number; detail: string }[]>([])
  // 💡 5日线每日分隔标识：透明 LineSeries 作载体(提供时间轴) + markers 插件实例承载每日日期标识
  const dailyDividerSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const dailyDividerMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const latestAnnotationRef = useRef<{ symbol: string; payload: ChartAnnotationPayload } | null>(null)
  const selectedSymbolRef = useRef(selectedSymbol)
  const themeRef = useRef(theme)
  useEffect(() => { selectedSymbolRef.current = selectedSymbol }, [selectedSymbol])
  useEffect(() => { themeRef.current = theme }, [theme])
  const workerRef = useIndicatorWorker()

  // PROD-02: 归一化标的用于跨格式匹配（US.AAPL / AAPL / 00700.HK）
  const normalizeSymbol = (s?: string | null) => (s || '').replace(/^(US|HK|SH|SZ|MARKET)\./i, '').toUpperCase()

  // 美东夏令时判定（3月第二个周日 ~ 11月第一个周日,K 线仅取 09:30+,故按天判定足够)
  const isUSDST = (year: number, month1to12: number, day: number): boolean => {
    const firstSundayOfMarch = ((8 - new Date(Date.UTC(year, 2, 1)).getUTCDay()) % 7) || 7
    const secondSundayOfMarch = firstSundayOfMarch + 7
    const firstSundayOfNovember = ((8 - new Date(Date.UTC(year, 10, 1)).getUTCDay()) % 7) || 7
    const ymd = year * 10000 + month1to12 * 100 + day
    return ymd >= year * 10000 + 3 * 100 + secondSundayOfMarch && ymd < year * 10000 + 11 * 100 + firstSundayOfNovember
  }

  // 将 'YYYY-MM-DD' 或数字转换为图表使用的 Unix 秒（UTCTimestamp）
  const toChartTime = (t: string | number): number | null => {
    if (typeof t === 'number') return t
    // 💡 futu 后端返回的 'YYYY-MM-DD HH:mm:ss' 是交易所本地时间（无时区标记）,
    // 直接 new Date('2026-08-14T14:30:00') 会被 JS 按运行环境本地时区解析,
    // 导致 PT 环境把美股 ET 14:30 误解为 PT 14:30 → X 轴挤左边。
    // 这里按标的交易所时区补齐时区偏移,再转 UTC 秒戳。
    const intradayMatch = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?/.exec(t)
    if (intradayMatch) {
      const [, y, mo, d, hh, mm, ss] = intradayMatch
      const isHK = /\.(HK)$|^HK\./i.test(selectedSymbol || '')
      const tzOffsetMin = isHK
        ? 8 * 60
        : isUSDST(+y, +mo, +d) ? -240 : -300
      let tsMs = Date.UTC(+y, +mo - 1, +d, +hh, +mm, +(ss || '0')) - tzOffsetMin * 60_000
      // 💡 港股午休 12:00-13:00（当地）从 X 轴扣除：下午段(>=13:00)整体前移 1h，使 12:00 后紧贴 13:00
      if (isHK && (+hh * 60 + +mm) >= 13 * 60) tsMs -= 3600_000
      return Math.floor(tsMs / 1000)
    }
    // 回退:纯日期 'YYYY-MM-DD' → UTC 00:00（兼容日K线历史数据）
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t)
    if (m) return Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3]) / 1000)
    const n = Number(t)
    return Number.isFinite(n) ? n : null
  }

  // PROD-02: 将当前 AI 标注渲染到 K 线图（箭头 + 价格线 + 区域带）
  const applyAiAnnotations = () => {
    if (aiMarkersApiRef.current) aiMarkersApiRef.current.setMarkers([])
    aiPriceLinesRef.current.forEach((pl) => seriesRef.current?.removePriceLine(pl))
    aiPriceLinesRef.current = []
    aiZoneSeriesRef.current.forEach((s) => chartRef.current?.removeSeries(s))
    aiZoneSeriesRef.current = []
    aiSignalsClickRef.current = []

    const ann = latestAnnotationRef.current
    const series = seriesRef.current
    const chart = chartRef.current
    if (!ann || !series || !chart) return
    if (normalizeSymbol(ann.symbol) !== normalizeSymbol(selectedSymbolRef.current)) return

    const payload = ann.payload

    // 1) 买卖信号 -> 箭头 markers
    const signals = payload.signals || []
    if (signals.length) {
      const markers = signals
        .map((sig): SeriesMarker<Time> | null => {
          const t = toChartTime(sig.time)
          if (t == null) return null
          const price = sig.price
          aiSignalsClickRef.current.push({
            time: t,
            detail: `${sig.side === 'buy' ? '🟢 AI 买入信号' : '🔴 AI 卖出信号'}${sig.label ? ' · ' + sig.label : ''}${price != null ? ' @ ' + price : ''}`,
          })
          return {
            time: t as Time,
            position: sig.side === 'buy' ? 'belowBar' : 'aboveBar',
            color: sig.side === 'buy' ? '#10b981' : '#ef4444',
            shape: sig.side === 'buy' ? 'arrowUp' : 'arrowDown',
            text: sig.label || (sig.side === 'buy' ? 'B' : 'S'),
          }
        })
        .filter((m): m is SeriesMarker<Time> => m !== null)
        .sort((a, b) => (a.time as number) - (b.time as number))
      if (markers.length) {
        if (!aiMarkersApiRef.current) aiMarkersApiRef.current = createSeriesMarkers(series, markers)
        else aiMarkersApiRef.current.setMarkers(markers)
      }
    }

    // 2) 支撑/压力/目标/止损 -> 价格线
    const levelColor: Record<string, string> = {
      support: MARKET_COLORS.bull,
      resistance: MARKET_COLORS.bear,
      target: SEMANTIC_COLORS.info,
      stop: SEMANTIC_COLORS.warn,
    }
    ;(payload.levels || []).forEach((lv) => {
      const pl = series.createPriceLine({
        price: lv.price,
        color: levelColor[lv.type] || '#8b5cf6',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: lv.label || lv.type.toUpperCase(),
      })
      aiPriceLinesRef.current.push(pl)
    })

    // 3) 区域高亮 -> 半透明基线带（baseline 介于 lower 与 upper 之间填充）
    ;(payload.zones || []).forEach((z) => {
      const band = z.color || 'rgba(139,92,246,0.16)'
      const zone = chart.addSeries(BaselineSeries, {
        topLineColor: 'rgba(0,0,0,0)',
        bottomLineColor: 'rgba(0,0,0,0)',
        topFillColor1: band,
        topFillColor2: band,
        bottomFillColor1: band,
        bottomFillColor2: band,
        lineWidth: 1,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceScaleId: 'right',
        baseValue: { type: 'price', price: z.lower },
      })
      const base = series.data() as { time: Time }[]
      zone.setData(base.map((d) => ({ time: d.time, value: z.upper })))
      aiZoneSeriesRef.current.push(zone)
    })
  }
  const applyAiAnnotationsRef = useRef(applyAiAnnotations)
  applyAiAnnotationsRef.current = applyAiAnnotations

  // PROD-02: 订阅 AI 标注 store，按标的匹配后渲染/清除
  const aiPayload = useChartAnnotationStore((s) => s.payload)
  const aiSymbol = useChartAnnotationStore((s) => s.symbol)
  useEffect(() => {
    latestAnnotationRef.current = aiSymbol && aiPayload ? { symbol: aiSymbol, payload: aiPayload } : null
    applyAiAnnotations()
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiPayload, aiSymbol, selectedSymbol, theme])

  // AI-01 能力②：形态识别叠加（与 AI 副驾标注相互独立，使用各自 ref 互不覆盖）
  const patternPriceLinesRef = useRef<IPriceLine[]>([])
  const patternZoneRef = useRef<ISeriesApi<'Baseline'>[]>([])
  const latestPatternRef = useRef<{ symbol: string; payload: ChartAnnotationPayload } | null>(null)

  const applyPatternAnnotations = () => {
    patternPriceLinesRef.current.forEach((pl) => seriesRef.current?.removePriceLine(pl))
    patternPriceLinesRef.current = []
    patternZoneRef.current.forEach((s) => chartRef.current?.removeSeries(s))
    patternZoneRef.current = []

    const ann = latestPatternRef.current
    const series = seriesRef.current
    const chart = chartRef.current
    if (!ann || !series || !chart) return
    if (normalizeSymbol(ann.symbol) !== normalizeSymbol(selectedSymbolRef.current)) return

    const payload = ann.payload
    const levelColor: Record<string, string> = {
      support: MARKET_COLORS.bull,
      resistance: MARKET_COLORS.bear,
      target: SEMANTIC_COLORS.info,
      stop: SEMANTIC_COLORS.warn,
    }
    ;(payload.levels || []).forEach((lv) => {
      const pl = series.createPriceLine({
        price: lv.price,
        color: levelColor[lv.type] || '#8b5cf6',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: lv.label || lv.type.toUpperCase(),
      })
      patternPriceLinesRef.current.push(pl)
    })
    ;(payload.zones || []).forEach((z) => {
      const band = z.color || 'rgba(139,92,246,0.12)'
      const zone = chart.addSeries(BaselineSeries, {
        topLineColor: 'rgba(0,0,0,0)',
        bottomLineColor: 'rgba(0,0,0,0)',
        topFillColor1: band,
        topFillColor2: band,
        bottomFillColor1: band,
        bottomFillColor2: band,
        lineWidth: 1,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceScaleId: 'right',
        baseValue: { type: 'price', price: z.lower },
      })
      const base = series.data() as { time: Time }[]
      zone.setData(base.map((d) => ({ time: d.time, value: z.upper })))
      patternZoneRef.current.push(zone)
    })
  }
  const applyPatternAnnotationsRef = useRef(applyPatternAnnotations)
  applyPatternAnnotationsRef.current = applyPatternAnnotations

  // AI-01 能力②：订阅形态标注 store，按标的匹配后渲染/清除
  const patternPayload = usePatternStore((s) => s.payload)
  const patternSymbol = usePatternStore((s) => s.symbol)
  useEffect(() => {
    latestPatternRef.current = patternSymbol && patternPayload ? { symbol: patternSymbol, payload: patternPayload } : null
    applyPatternAnnotations()
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patternPayload, patternSymbol, selectedSymbol, theme])

  const measureBoxRef = useRef<HTMLDivElement>(null)
  const measureInfoRef = useRef<HTMLDivElement>(null)
  const measurePriceRef = useRef<HTMLDivElement>(null)
  const measurePctRef = useRef<HTMLDivElement>(null)
  const currentCrosshairRef = useRef<{ point: {x: number, y: number}, time: any, price: number } | null>(null)
  const isCrosshairActiveRef = useRef(false)
  const oRef = useRef<HTMLSpanElement>(null)
  const hRef = useRef<HTMLSpanElement>(null)
  const lRef = useRef<HTMLSpanElement>(null)
  const cRef = useRef<HTMLSpanElement>(null)
  const vRef = useRef<HTMLSpanElement>(null)
  const updateOhlcvDomRef = useRef<(data: any) => void>(undefined)

  updateOhlcvDomRef.current = (data: any) => {
    if (!data) return
    if (oRef.current) oRef.current.textContent = Number(data.open).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (hRef.current) hRef.current.textContent = Number(data.high).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (lRef.current) lRef.current.textContent = Number(data.low).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (cRef.current) cRef.current.textContent = Number(data.close).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (vRef.current) {
      const v = Number(data.volume || 0)
      vRef.current.textContent = v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(2)}K` : v.toString()
    }
  }

  useEffect(() => {
    isFirstLoadFittedRef.current = false
  }, [selectedSymbol, selectedPeriod])

  useEffect(() => {
    const handleTick = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const cleanSym = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '');

      if (cleanSym(detail.ticker) === cleanSym(selectedSymbol)) {
        const lastPrice = parseFloat(detail.last_price);
        if (!isNaN(lastPrice) && lastPrice > 0) {
          // 💡 Tick 模式:父组件没有 seriesRef,但需要刷新顶部 OHLCV 行
          if (selectedPeriod === 'tick') {
            // 维护内存中的 latestCandle 以便 OHLCV 面板跟随实时更新
            if (!lastCandleRef.current) {
              lastCandleRef.current = { time: Math.floor(Date.now() / 1000), open: lastPrice, high: lastPrice, low: lastPrice, close: lastPrice, volume: 0 }
            } else {
              lastCandleRef.current.high = Math.max(lastCandleRef.current.high, lastPrice)
              lastCandleRef.current.low = Math.min(lastCandleRef.current.low, lastPrice)
              lastCandleRef.current.close = lastPrice
            }
            if (updateOhlcvDomRef.current && !isCrosshairActiveRef.current) {
              updateOhlcvDomRef.current(lastCandleRef.current)
            }
            return
          }
          if (seriesRef.current && lastCandleRef.current) {
            const current = lastCandleRef.current;
            current.close = lastPrice; current.high = Math.max(current.high, lastPrice); current.low = Math.min(current.low, lastPrice);
            if (document.hidden) return;
            seriesRef.current.update(current);
            if (volumeRef.current) {
              const isUp = current.close >= current.open;
              volumeRef.current.update({ time: current.time, value: current.volume || 0, color: isUp ? (theme === 'dark' ? 'rgba(16, 185, 129, 0.5)' : 'rgba(5, 150, 105, 0.5)') : (theme === 'dark' ? 'rgba(239, 68, 68, 0.5)' : 'rgba(220, 38, 38, 0.5)') });
            }
            if (currentPriceLineRef.current) currentPriceLineRef.current.applyOptions({ price: lastPrice });
            if (updateOhlcvDomRef.current && !isCrosshairActiveRef.current) updateOhlcvDomRef.current(current);
          }
        }
      }
    };
    window.addEventListener('market_tick', handleTick);
    return () => window.removeEventListener('market_tick', handleTick);
  }, [selectedSymbol, theme, selectedPeriod]);

  useEffect(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) chartRef.current.remove()

    // 💡 Tick 图模式使用独立的 HighFreqChartWrapper 组件，不创建主图表
    if (selectedPeriod === 'tick') {
      chartRef.current = null
      return
    }

    // 💡 分时线/五日线禁止缩放，日K及以上周期允许缩放（限制缩放范围）
    const isIntraday = ['1m', '5m'].includes(selectedPeriod)
    const disableZoom = isIntraday
    // 分时/5日使用较小间距以展示全天刻度，日K及以上使用默认间距
    const fixedBarSpacing = isIntraday ? 3 : 10
    // 💡 日K及以上周期缩放范围限制：最小2（放大），最大20（缩小）
    const minBarSpacing = disableZoom ? fixedBarSpacing : 2
    const maxBarSpacing = disableZoom ? fixedBarSpacing : 20

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: theme === 'dark' ? '#94a3b8' : '#64748b' },
      grid: { vertLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' }, horzLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' } },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderColor: theme === 'dark' ? '#475569' : '#cbd5e1', autoScale: true, scaleMargins: { top: 0.1, bottom: 0.40 } },
      // 💡 分时线/5日线禁止左右拖动：关闭水平滚动 + 固定左右边界
      handleScroll: { mouseWheel: true, pressedMouseMove: !isIntraday, horzTouchDrag: !isIntraday, vertTouchDrag: true },
      // 💡 K线图左右拖动配置：允许拖动但不超过K线数据最大最小值
      timeScale: {
        borderColor: theme === 'dark' ? '#475569' : '#cbd5e1',
        timeVisible: true,
        fixLeftEdge: true,      // 固定左边界，不允许拖动超过数据起点
        fixRightEdge: true,     // 分时线/5日线固定右边界，禁止左右拖动（不允许右侧空白偏移）
        rightOffset: selectedPeriod === '1m' ? 10 : 0,         // 仅分时线右侧留空展示；5日线/日K以上不留空以免可拖
        barSpacing: fixedBarSpacing,         // 分时/日K及以上使用固定间距
        minBarSpacing: minBarSpacing,        // 缩放下限
        maxBarSpacing: maxBarSpacing,        // 缩放上限
        // 💡 5日 K 线跨多天, 强制 tick 标签带日期(默认 lwc 只在跨日期时偶发加日期,容易看不到)
        // 显示按标的交易所本地时区 (港股=HKT UTC+8, 美股=ET UTC-5/-4)
                tickMarkFormatter: (time: number) => {
                  const isHK = /\.(HK)$|^HK\./i.test(selectedSymbol || '')
                  const d = new Date(time * 1000)
                  // 把 UTC 毫秒转为交易所本地时间(直接加偏移,再以 UTC 方法取年月日时分)
                  const useDST = isHK ? false : isUSDST(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate())
                  const offsetMs = isHK ? 8 * 3600 * 1000 : (useDST ? -4 * 3600 * 1000 : -5 * 3600 * 1000)
                  // 💡 港股午休压缩数据: 下午段 time 已减 1h, 这里 hour>=12 即真实 13:00 起, 还原 +1h 使刻度显示真实 13:00-16:00
                  const displayMs = isHK && (d.getTime() + offsetMs) >= 0 && new Date(d.getTime() + offsetMs).getUTCHours() >= 12
                    ? d.getTime() + offsetMs + 3600_000
                    : d.getTime() + offsetMs
                  const l = new Date(displayMs)
                  const M = (l.getUTCMonth() + 1).toString().padStart(2, '0')
                  const D = l.getUTCDate().toString().padStart(2, '0')
                  const h = l.getUTCHours().toString().padStart(2, '0')
                  const m = l.getUTCMinutes().toString().padStart(2, '0')
                  // 周K/月K 一格代表多日时,仅显示 MM-DD;日内格仅显示 HH:mm;跨天格显示 MM-DD HH:mm
                  if (selectedPeriod === '1d' || selectedPeriod === '1w' || selectedPeriod === '1M') {
                    return `${M}-${D}`
                  }
                  if (selectedPeriod === '1m' || selectedPeriod === '5m') {
                    return `${M}-${D} ${h}:${m}`
                  }
                  return `${h}:${m}`
                },
      },
    })

    const bbUpperLine = chart.addSeries(AreaSeries, { lineColor: theme === 'dark' ? 'rgba(251, 191, 36, 0.4)' : 'rgba(217, 119, 6, 0.4)', topColor: theme === 'dark' ? 'rgba(251, 191, 36, 0.15)' : 'rgba(217, 119, 6, 0.15)', bottomColor: 'rgba(0, 0, 0, 0)', lineWidth: 1, lineStyle: LineStyle.Dashed, crosshairMarkerVisible: false })
    const bbLowerLine = chart.addSeries(LineSeries, { color: theme === 'dark' ? 'rgba(251, 191, 36, 0.4)' : 'rgba(217, 119, 6, 0.4)', lineWidth: 1, lineStyle: LineStyle.Dashed, crosshairMarkerVisible: false })
    const candlestickSeries = chart.addSeries(CandlestickSeries, { upColor: MARKET_COLORS.bull, downColor: MARKET_COLORS.bear, borderVisible: false, wickUpColor: MARKET_COLORS.bull, wickDownColor: MARKET_COLORS.bear })
    // 💡 5日线每日分隔竖线载体：透明 LineSeries (线不可见, 仅承载 vertical_line markers, 避免与 AI markers 共用同一 series 冲突)
    const dailyDividerSeries = chart.addSeries(LineSeries, {
      color: 'rgba(0,0,0,0)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, priceScaleId: 'right',
    });
    dailyDividerSeriesRef.current = dailyDividerSeries
    dailyDividerMarkersRef.current = createSeriesMarkers(dailyDividerSeries, [])
    const ma20Line = chart.addSeries(LineSeries, { color: '#f472b6', lineWidth: 2, crosshairMarkerVisible: false })
    const ma50Line = chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 2, crosshairMarkerVisible: false })
    const ma200Line = chart.addSeries(LineSeries, { color: '#fbbf24', lineWidth: 2, crosshairMarkerVisible: false })
    const volumeSeries = chart.addSeries(HistogramSeries, { color: '#26a69a', priceFormat: { type: 'volume' }, priceScaleId: '' })
    chart.priceScale('').applyOptions({ scaleMargins: { top: 0.62, bottom: 0.26 } })
    const macdHistSeries = chart.addSeries(HistogramSeries, { priceScaleId: 'macd' })
    const macdDiffSeries = chart.addSeries(LineSeries, { color: theme === 'dark' ? '#38bdf8' : '#0284c7', lineWidth: 1, priceScaleId: 'macd', crosshairMarkerVisible: false })
    const macdDeaSeries = chart.addSeries(LineSeries, { color: theme === 'dark' ? '#fbbf24' : '#d97706', lineWidth: 1, priceScaleId: 'macd', crosshairMarkerVisible: false })
    chart.priceScale('macd').applyOptions({ scaleMargins: { top: 0.76, bottom: 0.13 } })
    const rsiHistSeries = chart.addSeries(HistogramSeries, { priceScaleId: 'rsi', base: 50 })
    const rsiLineSeries = chart.addSeries(LineSeries, { color: theme === 'dark' ? '#a78bfa' : '#8b5cf6', lineWidth: 1, priceScaleId: 'rsi', crosshairMarkerVisible: false })
    chart.priceScale('rsi').applyOptions({ scaleMargins: { top: 0.88, bottom: 0 } })
    const kdjKSeries = chart.addSeries(LineSeries, { color: theme === 'dark' ? '#f8fafc' : '#475569', lineWidth: 1, priceScaleId: 'rsi', crosshairMarkerVisible: false })
    const kdjDSeries = chart.addSeries(LineSeries, { color: '#fbbf24', lineWidth: 1, priceScaleId: 'rsi', crosshairMarkerVisible: false })
    const kdjJSeries = chart.addSeries(LineSeries, { color: '#f472b6', lineWidth: 1, priceScaleId: 'rsi', crosshairMarkerVisible: false })
    const priceLine = candlestickSeries.createPriceLine({ price: 0, color: theme === 'dark' ? '#38bdf8' : '#0284c7', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '现价' })

    chartRef.current = chart; seriesRef.current = candlestickSeries; ma20Ref.current = ma20Line; ma50Ref.current = ma50Line; ma200Ref.current = ma200Line; bbUpperRef.current = bbUpperLine; bbLowerRef.current = bbLowerLine; macdDiffRef.current = macdDiffSeries; macdDeaRef.current = macdDeaSeries; macdHistRef.current = macdHistSeries; rsiLineRef.current = rsiLineSeries; rsiHistRef.current = rsiHistSeries; kdjKRef.current = kdjKSeries; kdjDRef.current = kdjDSeries; kdjJRef.current = kdjJSeries; volumeRef.current = volumeSeries; currentPriceLineRef.current = priceLine;

    // PROD-12: 注册跨图表十字线同步；applyExternal 收到同源广播时设到本图（带防回环锁）
    crosshairSync.register(syncGroup, chartIdRef.current, (pos) => {
      if (!chartRef.current || !seriesRef.current) return
      isExternalSyncRef.current = true
      try {
        if (pos.time == null || pos.price == null) {
          chartRef.current.clearCrosshairPosition()
        } else {
          chartRef.current.setCrosshairPosition(pos.price, pos.time, seriesRef.current)
        }
      } finally {
        isExternalSyncRef.current = false
      }
    })

    // PROD-09: 图表初始化后绘制模拟持仓价格线
    applyPositionLines()
    // PROD-11: 图表重建后若已有 K 线数据，重新叠加自定义指标
    if (currentBarsRef.current.length) applyCIPanelRef.current(currentBarsRef.current)

    const handleResize = (entries: ResizeObserverEntry[]) => {
      if (entries.length === 0 || !chartRef.current) return
      const newRect = entries[0].contentRect
      requestAnimationFrame(() => {
        if (chartRef.current) {
          chartRef.current.applyOptions({ width: newRect.width, height: newRect.height })
          // 💡 分时/日K及以上周期保持固定缩放值，不随窗口大小调整
          if (dataLengthRef.current > 0 && !disableZoom) {
            chartRef.current.timeScale().applyOptions({ minBarSpacing: Math.max(0.1, newRect.width / dataLengthRef.current) })
          }
        }
      })
    }
    const ro = new ResizeObserver(handleResize); ro.observe(chartContainerRef.current)
    const container = chartContainerRef.current as any;

    const updateMeasureDOM = (start: any, end: any) => {
      if (!measureBoxRef.current || !measureInfoRef.current) return;
      const left = Math.min(start.point.x, end.point.x); const top = Math.min(start.point.y, end.point.y); const width = Math.abs(start.point.x - end.point.x); const height = Math.abs(start.point.y - end.point.y);
      measureBoxRef.current.style.left = `${left}px`; measureBoxRef.current.style.top = `${top}px`; measureBoxRef.current.style.width = `${width}px`; measureBoxRef.current.style.height = `${height}px`;
      const priceDiff = end.price - start.price; const pctDiff = (priceDiff / start.price) * 100;
      if (measurePriceRef.current) { measurePriceRef.current.textContent = `${priceDiff >= 0 ? '+' : ''}${priceDiff.toFixed(2)}`; measurePriceRef.current.className = priceDiff >= 0 ? 'font-bold text-emerald-500' : 'font-bold text-red-500'; }
      if (measurePctRef.current) { measurePctRef.current.textContent = `${priceDiff >= 0 ? '+' : ''}${pctDiff.toFixed(2)}%`; measurePctRef.current.className = priceDiff >= 0 ? 'text-emerald-500' : 'text-red-500'; }
      const infoX = Math.min(end.point.x + 15, container.clientWidth - 80); const infoY = Math.min(end.point.y + 15, container.clientHeight - 40);
      measureInfoRef.current.style.left = `${infoX}px`; measureInfoRef.current.style.top = `${infoY}px`;
    };

    chart.subscribeCrosshairMove((param) => {
      // PROD-12: 由外部同步触发的 crosshair 事件直接跳过，防止回环广播
      if (isExternalSyncRef.current) return

      const isValid = param.point && param.time && param.point.x >= 0 && param.point.x <= chartContainerRef.current!.clientWidth && param.point.y >= 0 && param.point.y <= chartContainerRef.current!.clientHeight;
      isCrosshairActiveRef.current = !!isValid;
      if (isValid) {
        const price = candlestickSeries.coordinateToPrice(param.point!.y);
        currentCrosshairRef.current = { point: param.point!, time: param.time, price: price! };
        if (container._isMeasuring && container._measureStart) updateMeasureDOM(container._measureStart, currentCrosshairRef.current);
      } else { currentCrosshairRef.current = null; }

      if (isDrawModeRef.current && (chartContainerRef.current as any)._activeDrawingPlugin && isValid) {
        const price = candlestickSeries.coordinateToPrice(param.point!.y);
        if (price !== null) (chartContainerRef.current as any)._activeDrawingPlugin.updateEndPoint(param.time, price);
      }
      // PROD-09: 下单拖拽 -> 实时更新预览线；持仓线拖拽 -> 实时跟随
      const c9 = chartContainerRef.current as any
      if (c9._isOrderDragging && isValid) {
        const dp = candlestickSeries.coordinateToPrice(param.point!.y)
        if (dp != null && orderPreviewLineRef.current) { orderPreviewLineRef.current.applyOptions({ price: dp }); c9._orderDragPrice = dp }
      }
      if (c9._dragLevel && isValid) {
        const dp = candlestickSeries.coordinateToPrice(param.point!.y)
        if (dp != null) { c9._dragLevel.line.applyOptions({ price: dp }); c9._dragLevelPrice = dp }
      }
      if (isValid) {
        const cData = param.seriesData.get(candlestickSeries) as any; const vData = param.seriesData.get(volumeSeries) as any;
        if (cData && updateOhlcvDomRef.current) updateOhlcvDomRef.current({ ...cData, volume: vData?.value || 0 });
        // PROD-12: 广播十字线位置给同组其他图表（同标的多周期 -> Y 对齐；异标的 -> 时间对齐）
        const broadcastPrice = cData ? cData.close : (candlestickSeries.coordinateToPrice(param.point!.y) ?? 0)
        crosshairSync.broadcast(chartIdRef.current, syncGroup, { time: param.time as Time, price: broadcastPrice });
      } else {
        if (lastCandleRef.current && updateOhlcvDomRef.current) updateOhlcvDomRef.current(lastCandleRef.current);
        // PROD-12: 鼠标移出 -> 通知同组图表清除同步十字线
        crosshairSync.broadcast(chartIdRef.current, syncGroup, { time: null, price: null });
      }
    });

    chart.subscribeClick((param) => {
      if (param.time && markersRef.current) {
        const clickedMarker = markersRef.current.find(m => m.time === param.time)
        if (clickedMarker && clickedMarker.detail) toast({ title: `📊 信号触发 (${new Date((param.time as number) * 1000).toLocaleString('zh-CN', { hour12: false })})`, description: clickedMarker.detail })
      }
      // PROD-02: AI 标注信号点击提示
      if (param.time && aiSignalsClickRef.current) {
        const aiMarker = aiSignalsClickRef.current.find(m => m.time === param.time)
        if (aiMarker) toast({ title: `🤖 AI 标注 (${(param.time as number)})`, description: aiMarker.detail })
      }
      if (drawToolRef.current === 'none' || !param.point) return;
      const price = candlestickSeries.coordinateToPrice(param.point.y);
      if (price === null) return;
      const container = chartContainerRef.current as any;
      const tool = drawToolRef.current;
      const color = theme === 'dark' ? '#38bdf8' : '#0284c7';
      if (!container._activeDrawingPlugin) {
        if (tool === 'hline') {
          const p = new HLinePrimitive(candlestickSeries, param.time ?? null, price, color);
          candlestickSeries.attachPrimitive(p); drawingsRef.current.push(p);
          container._activeDrawingPlugin = null; setDrawTool('none');
        } else {
          if (!param.time) return;
          if (tool === 'trendline') {
            container._activeDrawingPlugin = new TrendLinePrimitive(chart, candlestickSeries, param.time, price, color);
          } else if (tool === 'rect') {
            container._activeDrawingPlugin = new RectanglePrimitive(chart, candlestickSeries, param.time, price, color);
          } else if (tool === 'fib') {
            container._activeDrawingPlugin = new FibRetracementPrimitive(candlestickSeries, param.time, price, color);
          }
          candlestickSeries.attachPrimitive(container._activeDrawingPlugin);
        }
      } else {
        if (!param.time) return;
        container._activeDrawingPlugin.updateEndPoint(param.time, price);
        drawingsRef.current.push(container._activeDrawingPlugin);
        container._activeDrawingPlugin = null; setDrawTool('none');
      }
    });

    const handleMouseDown = (e: MouseEvent) => {
      const c = chartContainerRef.current as any
      if (e.shiftKey && currentCrosshairRef.current) {
        c._isMeasuring = true; c._measureStart = currentCrosshairRef.current;
        if (measureBoxRef.current) measureBoxRef.current.style.display = 'block';
        if (measureInfoRef.current) measureInfoRef.current.style.display = 'flex';
        updateMeasureDOM(c._measureStart, currentCrosshairRef.current);
        return;
      }
      // PROD-09: 下单模式 -> 拖拽设置价格线（松手弹确认框）
      if (orderModeRef.current && currentCrosshairRef.current) {
        const p0 = candlestickSeries.coordinateToPrice(currentCrosshairRef.current.point.y)
        if (p0 != null) {
          c._isOrderDragging = true; c._orderDragPrice = p0
          orderPreviewLineRef.current = candlestickSeries.createPriceLine({ price: p0, color: '#a855f7', lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '拖拽下单' })
        }
        return;
      }
      // PROD-09: 命中持仓线 (entry/sl/tp) -> 拖拽调整
      if (!isDrawModeRef.current && currentCrosshairRef.current && seriesRef.current) {
        const my = currentCrosshairRef.current.point.y
        const positions = useTradeStore.getState().positions[selectedSymbol] ?? []
        for (const pos of positions) {
          for (const lvl of (['entryPrice', 'sl', 'tp'] as const)) {
            const val = pos[lvl]
            if (val == null) continue
            const ly = seriesRef.current!.priceToCoordinate(val)
            if (ly != null && Math.abs(ly - my) < 6) {
              const line = positionLinesRef.current[`${pos.id}:${lvl}`]
              if (line) { c._dragLevel = { posId: pos.id, level: lvl, line }; return }
            }
          }
        }
      }
      if (measureBoxRef.current) measureBoxRef.current.style.display = 'none';
      if (measureInfoRef.current) measureInfoRef.current.style.display = 'none';
      c._isMeasuring = false;
    };
    const handleMouseUp = () => {
      const c = chartContainerRef.current as any
      if (c?._isMeasuring) c._isMeasuring = false
      // PROD-09: 完成下单拖拽 -> 弹出确认框（沙箱）
      if (c?._isOrderDragging) {
        c._isOrderDragging = false
        const finalPrice = c._orderDragPrice ?? null
        if (orderPreviewLineRef.current) { try { seriesRef.current?.removePriceLine(orderPreviewLineRef.current) } catch { /* 图表对象可能已销毁，detach/remove 失败可安全忽略 */ }; orderPreviewLineRef.current = null }
        if (finalPrice != null) {
          const last = lastCandleRef.current?.close
          const side: OrderSide = last != null && finalPrice < last ? 'BUY' : 'SELL'
          useTradeStore.getState().setPending({ symbol: selectedSymbol, side, type: 'LIMIT', price: finalPrice, qty: 100 })
        }
      }
      // PROD-09: 完成持仓线拖拽 -> 提交到 store
      if (c?._dragLevel) {
        const dl = c._dragLevel
        const price = c._dragLevelPrice
        c._dragLevel = null; c._dragLevelPrice = null
        if (price != null) useTradeStore.getState().updatePositionLevel(selectedSymbol, dl.posId, dl.level, price)
        else applyPositionLines()
      }
    };
    container.addEventListener('mousedown', handleMouseDown); window.addEventListener('mouseup', handleMouseUp);

    return () => {
      ro.disconnect();
      // PROD-02: 旧图表销毁前清空 AI 标注引用，避免跨实例 removeSeries 报错
      if (aiMarkersApiRef.current) aiMarkersApiRef.current.setMarkers([])
      aiMarkersApiRef.current = null
      aiPriceLinesRef.current = []
      aiZoneSeriesRef.current = []
      aiSignalsClickRef.current = []
      chart.remove(); chartRef.current = null; seriesRef.current = null; volumeRef.current = null; macdDiffRef.current = null; macdDeaRef.current = null; macdHistRef.current = null; rsiLineRef.current = null; rsiHistRef.current = null; kdjKRef.current = null; kdjDRef.current = null; kdjJRef.current = null; bbUpperRef.current = null; bbLowerRef.current = null;       container.removeEventListener('mousedown', handleMouseDown); window.removeEventListener('mouseup', handleMouseUp);
      clearPositionLines();
      orderPreviewLineRef.current = null
      customMarkersApiRef.current = null
      customLineRefs.current = {}
    }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, applyPositionLines])

  // PROD-03: 切换标的/周期时清除已画线，避免点位错位误导
  useEffect(() => {
    clearDrawings()
    setDrawTool('none')
  }, [selectedSymbol, selectedPeriod, clearDrawings])

  // PROD-09: 订阅模拟持仓变化 -> 重绘 entry/SL/TP 价格线
  useEffect(() => {
    const unsub = useTradeStore.subscribe(() => applyPositionLines())
    applyPositionLines()
    return () => { unsub(); clearPositionLines() }
  }, [selectedSymbol, applyPositionLines, clearPositionLines])

  // PROD-11: 订阅自定义指标变化 -> 实时重算叠加
  useEffect(() => {
    const unsub = useCustomIndicatorStore.subscribe(() => {
      if (currentBarsRef.current.length) applyCIPanelRef.current(currentBarsRef.current)
    })
    return unsub
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    if (!realHistory.length) {
      seriesRef.current.setData([]); if (ma20Ref.current) ma20Ref.current.setData([]); if (ma50Ref.current) ma50Ref.current.setData([]); if (ma200Ref.current) ma200Ref.current.setData([]); if (bbUpperRef.current) bbUpperRef.current.setData([]); if (bbLowerRef.current) bbLowerRef.current.setData([]); if (volumeRef.current) volumeRef.current.setData([]); if (macdDiffRef.current) macdDiffRef.current.setData([]); if (macdDeaRef.current) macdDeaRef.current.setData([]); if (macdHistRef.current) macdHistRef.current.setData([]); if (rsiLineRef.current) rsiLineRef.current.setData([]); if (rsiHistRef.current) rsiHistRef.current.setData([]); if (kdjKRef.current) kdjKRef.current.setData([]); if (kdjDRef.current) kdjDRef.current.setData([]); if (kdjJRef.current) kdjJRef.current.setData([]); if (dailyDividerSeriesRef.current) { dailyDividerSeriesRef.current.setData([]); dailyDividerMarkersRef.current?.setMarkers([]) }
      if (oRef.current) oRef.current.textContent = '--'; if (hRef.current) hRef.current.textContent = '--'; if (lRef.current) lRef.current.textContent = '--'; if (cRef.current) cRef.current.textContent = '--'; if (vRef.current) vRef.current.textContent = '--'; lastCandleRef.current = null; return
    }

    const sortedHistoryAll = [...realHistory].sort((a, b) => new Date(a.time.replace(/-/g, '/')).getTime() - new Date(b.time.replace(/-/g, '/')).getTime())
    // 💡 分时线只展示当日数据，左侧从开盘开始，右侧到收盘
    const isIntradayPeriod = ['1m'].includes(selectedPeriod)
    const sortedHistory = isIntradayPeriod ? (() => {
      const now = new Date()
      const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      return sortedHistoryAll.filter(k => k.time.startsWith(todayStr))
    })() : sortedHistoryAll

    if (!workerRef.current) return
    const reqId = Date.now() + Math.random()

    workerRef.current.onmessage = (e: any) => {
      if (e.data.id !== reqId) return
      const { ma20, ma50, ma200, bb, macdCalc, rsiCalc, kdjCalc } = e.data
      const markers: any[] = []
      const rawLwData = sortedHistory
        .map((k, i) => {
          const timestamp = toChartTime(k.time)
          if (timestamp == null) return null
          const o = Number(k.open), h = Number(k.high), l = Number(k.low), c = Number(k.close)
          // 过滤 OHLC 含 NaN/非数字的脏 bar，避免 lightweight-charts setData 抛错
          if (![o, h, l, c].every((v) => Number.isFinite(v))) return null
          const point: any = { time: timestamp as UTCTimestamp, open: o, high: h, low: l, close: c, volume: Number(k.volume) || 0 }
          if (i >= 5 && rsiCalc[i] !== '-' && rsiCalc[i - 1] !== '-' && kdjCalc.k[i] !== '-' && kdjCalc.k[i - 1] !== '-') {
            const currClose = k.close; const prevClose = sortedHistory[i - 1].close; const minClose5 = Math.min(...sortedHistory.slice(i - 5, i).map((x) => x.close)); const maxClose5 = Math.max(...sortedHistory.slice(i - 5, i).map((x) => x.close)); const currRsi = Number(rsiCalc[i]); const prevRsi = Number(rsiCalc[i - 1]); const currMacdHist = Number(macdCalc.macd[i]); const prevMacdHist = Number(macdCalc.macd[i - 1]); const currK = Number(kdjCalc.k[i]); const prevK = Number(kdjCalc.k[i - 1]); const currD = Number(kdjCalc.d[i]); const prevD = Number(kdjCalc.d[i - 1]);
            const isNewLow = currClose < prevClose && currClose <= minClose5; const isNewHigh = currClose > prevClose && currClose >= maxClose5;
            const rsiBottom = isNewLow && currRsi > prevRsi && currRsi < 40; const macdBottom = isNewLow && currMacdHist < 0 && currMacdHist > prevMacdHist; const kdjGolden = currK > currD && prevK <= prevD && currK < 50;
            const rsiTop = isNewHigh && currRsi < prevRsi && currRsi > 60; const macdTop = isNewHigh && currMacdHist > 0 && currMacdHist < prevMacdHist; const kdjDeath = currK < currD && prevK >= prevD && currK > 50;
            const buySignals = []; if (rsiBottom) buySignals.push('RSI底背'); if (macdBottom) buySignals.push('MACD底背'); if (kdjGolden) buySignals.push('KDJ金叉');
            const sellSignals = []; if (rsiTop) sellSignals.push('RSI顶背'); if (macdTop) sellSignals.push('MACD顶背'); if (kdjDeath) sellSignals.push('KDJ死叉');
            if (buySignals.length > 0) {
              point.color = theme === 'dark' ? '#00ff88' : '#10b981'; point.wickColor = point.color; let buyDetail = `【买点特征】`; if (rsiBottom || macdBottom) { const sources = [rsiBottom ? 'RSI' : null, macdBottom ? 'MACD' : null].filter(Boolean).join('+'); buyDetail += `价格创新低 (${currClose.toFixed(2)})，但 ${sources} 指标拒绝创出新低并开始反转，暗示空头衰竭。`; } if (kdjGolden) { buyDetail += (rsiBottom || macdBottom ? '\n' : '') + `KDJ 在低位 (${currK.toFixed(1)}) 形成金叉，多头资金开始发力。`; } markers.push({ time: point.time, detail: buyDetail })
            } else if (sellSignals.length > 0) {
              point.color = theme === 'dark' ? '#ff0055' : '#ef4444'; point.wickColor = point.color; let sellDetail = `【卖点特征】`; if (rsiTop || macdTop) { const sources = [rsiTop ? 'RSI' : null, macdTop ? 'MACD' : null].filter(Boolean).join('+'); sellDetail += `价格创新高 (${currClose.toFixed(2)})，但 ${sources} 指标拒绝创出新高并开始反转，暗示多头衰竭。`; } if (kdjDeath) { sellDetail += (rsiTop || macdTop ? '\n' : '') + `KDJ 在高位 (${currK.toFixed(1)}) 形成死叉，空头抛压开始涌现。`; } markers.push({ time: point.time, detail: sellDetail })
            }
          }
          return point
        })
        .filter((p): p is NonNullable<typeof p> => p != null)

      // lightweight-charts 要求 time 严格升序且无重复，否则 setData 抛错导致图表崩溃。
      // 按 time 排序并去重，保证送入图表的 K 线数据合法。
      const seen = new Set<number>()
      const lwData = rawLwData
        .sort((a, b) => (a.time as number) - (b.time as number))
        .filter((p) => {
          if (seen.has(p.time as number)) return false
          seen.add(p.time as number)
          return true
        })
      const ma20Data: any[] = [], ma50Data: any[] = [], ma200Data: any[] = []; const bbUpperData: any[] = [], bbLowerData: any[] = []; const macdDiffData: any[] = [], macdDeaData: any[] = [], macdHistData: any[] = []; const rsiData: any[] = [], rsiHistData: any[] = []; const kdjKData: any[] = [], kdjDData: any[] = [], kdjJData: any[] = []; const volumeData: any[] = [];
      const upColor = theme === 'dark' ? 'rgba(16, 185, 129, 0.5)' : 'rgba(5, 150, 105, 0.5)'; const downColor = theme === 'dark' ? 'rgba(239, 68, 68, 0.5)' : 'rgba(220, 38, 38, 0.5)';
      for (let i = 0; i < lwData.length; i++) {
        const d = lwData[i]; const t = d.time;
        if (ma20[i] !== '-') ma20Data.push({ time: t, value: ma20[i] }); if (ma50[i] !== '-') ma50Data.push({ time: t, value: ma50[i] }); if (ma200[i] !== '-') ma200Data.push({ time: t, value: ma200[i] });
        if (bb.upper[i] !== '-') bbUpperData.push({ time: t, value: bb.upper[i] }); if (bb.lower[i] !== '-') bbLowerData.push({ time: t, value: bb.lower[i] });
        macdDiffData.push({ time: t, value: macdCalc.diff[i] }); macdDeaData.push({ time: t, value: macdCalc.dea[i] }); macdHistData.push({ time: t, value: macdCalc.macd[i], color: macdCalc.macd[i] >= 0 ? upColor : downColor });
        if (rsiCalc[i] !== '-') { rsiData.push({ time: t, value: rsiCalc[i] }); rsiHistData.push({ time: t, value: rsiCalc[i], color: rsiCalc[i] >= 50 ? upColor : downColor }); }
        if (kdjCalc.k[i] !== '-') kdjKData.push({ time: t, value: kdjCalc.k[i] }); if (kdjCalc.d[i] !== '-') kdjDData.push({ time: t, value: kdjCalc.d[i] }); if (kdjCalc.j[i] !== '-') kdjJData.push({ time: t, value: kdjCalc.j[i] });
        volumeData.push({ time: t, value: d.volume || 0, color: d.close >= d.open ? upColor : downColor });
      }
      seriesRef.current?.setData(lwData); markersRef.current = markers;
      // 💡 日/周/月线等日级以上周期：右边界固定贴最新数据(已 fixRightEdge), 加载后强制滚到实时端, 保证右边贴边缘且不可向左拖出右边界
      if (selectedPeriod !== '1m' && selectedPeriod !== '5m' && chartRef.current) {
        chartRef.current.timeScale().scrollToRealTime()
      }
      // 💡 5日线每日划分标识：每日首根 K 线顶部放带日期文字的 marker (lightweight-charts v5 原生 markers 无 vertical_line 形状, 用 square+text 标识相邻交易日)
      if (dailyDividerMarkersRef.current) {
        if (selectedPeriod === '5m' && lwData.length > 0) {
          const isHK = /\.(HK)$|^HK\./i.test(selectedSymbol || '')
          const localDayKey = (t: number) => {
            const d = new Date(t * 1000)
            const useDST = isHK ? false : isUSDST(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate())
            const offMs = isHK ? 8 * 3600 * 1000 : (useDST ? -4 * 3600 * 1000 : -5 * 3600 * 1000)
            const l = new Date(d.getTime() + offMs)
            const M = (l.getUTCMonth() + 1).toString().padStart(2, '0')
            const D = l.getUTCDate().toString().padStart(2, '0')
            const wd = ['日', '一', '二', '三', '四', '五', '六'][l.getUTCDay()]
            return { key: `${M}-${D}`, label: `${M}-${D} 周${wd}` }
          }
          const seen = new Set<string>()
          const dividerMarkers: SeriesMarker<Time>[] = []
          for (const p of lwData) {
            const day = localDayKey(p.time as number)
            if (!seen.has(day.key)) {
              seen.add(day.key)
              // 跳过最早一天(图左端无需标识), 仅对后续每个交易日首根画日期标识
              if (seen.size > 1) {
                dividerMarkers.push({ time: p.time, position: 'aboveBar', color: theme === 'dark' ? '#94a3b8' : '#64748b', shape: 'square', text: day.label, size: 0.6 })
              }
            }
          }
          dailyDividerSeriesRef.current?.setData(lwData.map((p) => ({ time: p.time, value: 0 })))
          dailyDividerMarkersRef.current.setMarkers(dividerMarkers)
        } else {
          dailyDividerSeriesRef.current?.setData([])
          dailyDividerMarkersRef.current.setMarkers([])
        }
      }
      // PROD-02: 数据重载后重新叠加 AI 标注
      applyAiAnnotationsRef.current?.()
      // AI-01 能力②: 数据重载后重新叠加形态识别标注
      applyPatternAnnotationsRef.current?.()
      if (ma20Ref.current) ma20Ref.current.setData(ma20Data); if (ma50Ref.current) ma50Ref.current.setData(ma50Data); if (ma200Ref.current) ma200Ref.current.setData(ma200Data); if (bbUpperRef.current) bbUpperRef.current.setData(bbUpperData); if (bbLowerRef.current) bbLowerRef.current.setData(bbLowerData); if (volumeRef.current) volumeRef.current.setData(volumeData); if (macdDiffRef.current) macdDiffRef.current.setData(macdDiffData); if (macdDeaRef.current) macdDeaRef.current.setData(macdDeaData); if (macdHistRef.current) macdHistRef.current.setData(macdHistData); if (rsiLineRef.current) rsiLineRef.current.setData(rsiData); if (rsiHistRef.current) rsiHistRef.current.setData(rsiHistData); if (kdjKRef.current) kdjKRef.current.setData(kdjKData); if (kdjDRef.current) kdjDRef.current.setData(kdjDData); if (kdjJRef.current) kdjJRef.current.setData(kdjJData)
      // PROD-11: K 线就绪后叠加自定义指标（数值线/布尔信号）
      currentBarsRef.current = sortedHistory
      applyCIPanelRef.current?.(sortedHistory);
      if (!isFirstLoadFittedRef.current && chartRef.current && lwData.length > 0) {
        requestAnimationFrame(() => {
          if (chartRef.current) {
            const isIntradayForRange = ['1m', '5m'].includes(selectedPeriod)
            const firstTime = lwData[0].time as number
            const lastTime = lwData[lwData.length - 1].time as number
            if (isIntradayForRange && lwData.length > 0) {
              // 💡 分时线/五日线: 左侧开盘, 右侧到收盘时间
              const isHK = /\.(HK)$|^HK\./i.test(selectedSymbol || '')
              const firstDate = new Date(firstTime * 1000)
              const lastDate = new Date(lastTime * 1000)
              const y1 = firstDate.getUTCFullYear(), m1 = firstDate.getUTCMonth(), d1 = firstDate.getUTCDate()
              const y2 = lastDate.getUTCFullYear(), m2 = lastDate.getUTCMonth(), d2 = lastDate.getUTCDate()
              const tzOffsetMin = isHK ? 8 * 60 : (isUSDST(y1, m1 + 1, d1) ? -240 : -300)
              const startUTC = Math.floor(Date.UTC(y1, m1, d1, 9, 30) - tzOffsetMin * 60_000) / 1000
              // 💡 港股午休 12:00-13:00 从 X 轴扣除：收盘端整体前移 1h（16:00 → 15:00），与 toChartTime 压缩一致
              const endHour = isHK ? 15 : 16
              const endMin = isHK ? 0 : 0
              const endUTC = Math.floor(Date.UTC(y2, m2, d2, endHour, endMin) - tzOffsetMin * 60_000) / 1000
              chartRef.current!.timeScale().setVisibleRange({
                from: startUTC as UTCTimestamp,
                to: endUTC as UTCTimestamp,
              })
            } else {
              // 💡 日线/周K/月K: 默认显示最近 ~120 根, 右边界贴住最后一条 K 线, 再留少量固定
              // offset 恰好够放「现价」axisLabel (数据已拉满, 用户可拖动/缩放查看全部历史)
              const visibleBars = 120
              chartRef.current!.timeScale().applyOptions({ rightOffset: 3 })
              const logicalFrom = Math.max(0, lwData.length - visibleBars)
              chartRef.current!.timeScale().setVisibleLogicalRange({
                from: logicalFrom as any,
                to: lwData.length as any,
              })
            }
          }
        })
        isFirstLoadFittedRef.current = true
      }
      dataLengthRef.current = lwData.length;
      // 💡 分时线/五日线保持固定缩放值，不随数据长度调整
      const isIntraday = ['1m', '5m'].includes(selectedPeriod);
      if (chartContainerRef.current && chartRef.current && lwData.length > 0 && !isIntraday) {
        chartRef.current.timeScale().applyOptions({ minBarSpacing: Math.max(0.1, chartContainerRef.current.clientWidth / lwData.length) });
      }
      if (lwData.length > 0) {
        lastCandleRef.current = { ...lwData[lwData.length - 1] }
        if (currentPriceLineRef.current) currentPriceLineRef.current.applyOptions({ price: lwData[lwData.length - 1].close })
        if (updateOhlcvDomRef.current && !isCrosshairActiveRef.current) updateOhlcvDomRef.current(lastCandleRef.current)
      }
    }
    workerRef.current.postMessage({ id: reqId, history: sortedHistory, params: { maPeriods: [20, 50, 200], bbParams: [20, 2], macdParams: [12, 26, 9], rsiPeriod: 14, kdjParams: [9, 3, 3] } })
    // PROD-12: 卸载或图表重建时从同步管理器注销，避免悬挂引用
// eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { crosshairSync.unregister(syncGroup, chartIdRef.current) }
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [realHistory, theme])

  useEffect(() => { if (ma20Ref.current) ma20Ref.current.applyOptions({ visible: showMA20 }); if (ma50Ref.current) ma50Ref.current.applyOptions({ visible: showMA50 }); if (ma200Ref.current) ma200Ref.current.applyOptions({ visible: showMA200 }); }, [showMA20, showMA50, showMA200])
  useEffect(() => { if (bbUpperRef.current) bbUpperRef.current.applyOptions({ visible: showBB }); if (bbLowerRef.current) bbLowerRef.current.applyOptions({ visible: showBB }); }, [showBB])
  useEffect(() => { if (macdHistRef.current) macdHistRef.current.applyOptions({ visible: showMACD }); if (macdDiffRef.current) macdDiffRef.current.applyOptions({ visible: showMACD }); if (macdDeaRef.current) macdDeaRef.current.applyOptions({ visible: showMACD }); }, [showMACD])
  useEffect(() => { if (rsiHistRef.current) rsiHistRef.current.applyOptions({ visible: showRSI }); if (rsiLineRef.current) rsiLineRef.current.applyOptions({ visible: showRSI }); }, [showRSI])
  useEffect(() => { if (kdjKRef.current) kdjKRef.current.applyOptions({ visible: showKDJ }); if (kdjDRef.current) kdjDRef.current.applyOptions({ visible: showKDJ }); if (kdjJRef.current) kdjJRef.current.applyOptions({ visible: showKDJ }); }, [showKDJ])

  const displayPrice = (realQuote && hasData) ? realQuote.last_price : selectedItem.price
  const displayChange = (realQuote && hasData) ? parseFloat(realQuote.change_pct) : selectedItem.change

  return (
    <div className="glass-card rounded-xl overflow-hidden flex flex-col h-full shadow-sm border-border/40">
      <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/10 flex items-center gap-3 flex-wrap shrink-0">
        {!isWatchlistExpanded && (
          <Button variant="outline" size="sm" onClick={toggleWatchlist} className="h-7 px-2.5 gap-1.5 text-[10px] border-border/50 bg-background" title="展开自选列表">
            <ChevronRight className="h-3.5 w-3.5" /> 自选
          </Button>
        )}
        <div className="flex items-center gap-1.5 bg-card border border-border/50 px-2.5 py-1 rounded-md shadow-sm" title={`Gateway: ${gatewayStatus}`}>
          <span className={cn("h-1.5 w-1.5 rounded-full", gatewayStatus === 'CONNECTED' ? 'bg-emerald-500 dark:bg-emerald-400' : 'bg-red-500 dark:bg-red-400')} />
          <span className="text-[9px] font-mono font-semibold text-muted-foreground">OpenD</span>
        </div>
        {realQuote?.source === 'mock' && (
          <div className="flex items-center gap-1 bg-red-500/10 border border-red-500/20 px-2 py-1 rounded-md shadow-sm animate-pulse mr-1" title="底层接口完全断开，当前显示沙箱模拟数据 (Mock)">
            <AlertTriangle className="h-3 w-3 text-red-500 dark:text-red-400" />
            <span className="text-[9px] font-mono font-bold text-red-500 dark:text-red-400">MOCK</span>
          </div>
        )}
        {realQuote?.source && realQuote.source.includes('yfinance') && (
          <div className="flex items-center gap-1 bg-indigo-500/10 border border-indigo-500/20 px-2 py-1 rounded-md shadow-sm mr-1" title="券商接口无权限，已平滑降级至 Yahoo Finance 兜底数据">
            <Globe className="h-3 w-3 text-indigo-500 dark:text-indigo-400" />
            <span className="text-[9px] font-mono font-bold text-indigo-500 dark:text-indigo-400">YF 兜底</span>
          </div>
        )}
        <span className="font-bold text-base tracking-tight ml-1">{selectedItem.symbol}</span>
        <span className={cn('text-lg font-bold font-mono tabular-nums', displayChange >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>{displayPrice.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
        <span className={cn('text-xs font-mono font-semibold flex items-center px-1.5 py-0.5 rounded-sm bg-background/50 border border-border/50', displayChange >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
          {displayChange >= 0 ? <TrendingUp className="h-3 w-3 mr-1" aria-hidden="true" /> : <TrendingDown className="h-3 w-3 mr-1" aria-hidden="true" />}
          {displayChange >= 0 ? '+' : ''}{displayChange.toFixed(2)}%
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="均线开关">
          <button onClick={() => setShowMA20(!showMA20)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showMA20 ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="MA20 (20日短期生命线)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#f472b6]", !showMA20 && "opacity-50")} />MA20</button>
          <button onClick={() => setShowMA50(!showMA50)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showMA50 ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="MA50 (50日中期分水岭)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#60a5fa]", !showMA50 && "opacity-50")} />MA50</button>
          <button onClick={() => setShowMA200(!showMA200)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showMA200 ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="MA200 (200日长期牛熊线)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#fbbf24]", !showMA200 && "opacity-50")} />MA200</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="指标开关">
          <button onClick={() => setShowBB(!showBB)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showBB ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="Bollinger Bands (布林带)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#d97706]", !showBB && "opacity-50")} />BB</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="MACD开关">
          <button onClick={() => setShowMACD(!showMACD)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showMACD ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="MACD (指数平滑异同移动平均线)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#38bdf8]", !showMACD && "opacity-50")} />MACD</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="RSI开关">
          <button onClick={() => setShowRSI(!showRSI)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showRSI ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="RSI (相对强弱指数)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[hsl(var(--ai))]", !showRSI && "opacity-50")} />RSI</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="KDJ开关">
          <button onClick={() => setShowKDJ(!showKDJ)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showKDJ ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="KDJ (随机指标)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#f472b6]", !showKDJ && "opacity-50")} />KDJ</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="K线周期">
          {periods.map((p, idx) => (<button key={p.id} onClick={() => setSelectedPeriod(p.id)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium', selectedPeriod === p.id ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} aria-pressed={selectedPeriod === p.id} title={`切换至${p.label}周期 (快捷键: ${idx + 1})`}>{p.label}</button>))}
        </div>
        <div className="flex items-center gap-0.5 border-l border-border/40 pl-1.5 ml-1">
          {DRAW_TOOLS.map((t) => (
            <Button key={t.id} variant={drawTool === t.id ? 'default' : 'outline'} size="sm" onClick={() => selectTool(t.id)} className={cn('h-7 w-7 p-0 text-[10px]', drawTool === t.id ? 'bg-primary text-primary-foreground shadow-sm shadow-primary/30' : 'border-border/50 bg-background')} title={t.label}>
              <t.icon className="h-3.5 w-3.5" />
            </Button>
          ))}
          <Button variant="outline" size="sm" onClick={clearDrawings} className="h-7 w-7 p-0 border-border/50 bg-background" title="清除全部画线"><Eraser className="h-3.5 w-3.5" /></Button>
          <Button variant={orderMode ? 'default' : 'outline'} size="sm" onClick={() => { const next = !orderMode; setOrderMode(next); if (next) setDrawTool('none') }} className={cn('relative h-7 w-7 p-0 border-border/50', orderMode ? 'bg-primary text-primary-foreground shadow-sm shadow-primary/30' : 'bg-background')} title={orderMode ? '退出下单模式' : '下单模式：在图上拖拽设置价格线'}><MousePointerClick className="h-3.5 w-3.5" />{positionCount > 0 && <span className="absolute -top-1.5 -right-1.5 min-w-[14px] h-[14px] px-0.5 rounded-full bg-emerald-500 text-[8px] font-bold text-white flex items-center justify-center">{positionCount}</span>}</Button>
          <Button variant={showCIPanel ? 'default' : 'outline'} size="sm" onClick={() => setShowCIPanel((s) => !s)} className={cn('h-7 w-7 p-0 border-border/50', showCIPanel ? 'bg-primary text-primary-foreground shadow-sm shadow-primary/30' : 'bg-background')} title={showCIPanel ? '关闭自定义指标' : '自定义指标脚本（Pine Script 简化版）'}><Sigma className="h-3.5 w-3.5" /></Button>
          <Button variant={showAlertSandbox ? 'default' : 'outline'} size="sm" onClick={() => setShowAlertSandbox((s) => !s)} className={cn('h-7 w-7 p-0 border-border/50', showAlertSandbox ? 'bg-primary text-primary-foreground shadow-sm shadow-primary/30' : 'bg-background')} title={showAlertSandbox ? '关闭条件单沙盒' : '条件单沙盒（ALERT-COND-01）'}><Bell className="h-3.5 w-3.5" /></Button>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowEvents(!showEvents)} className="h-7 px-2.5 gap-1.5 text-[10px] border-border/50 bg-background" title={showEvents ? '隐藏事件' : '显示事件'}>{showEvents ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}</Button>
      </div>
      {orderMode && (
        <div className="px-3 py-1 border-b border-border/30 bg-primary/10 text-[10px] font-mono text-primary flex items-center gap-1.5 shrink-0">
          <MousePointerClick className="h-3 w-3" /> 下单模式：在 K 线图上按住拖拽设置价格线，松手弹出模拟下单确认框（当前 OMS 未实装，仅沙箱推演）
        </div>
      )}
      <CustomIndicatorPanel open={showCIPanel} onClose={() => setShowCIPanel(false)} bars={currentBarsRef.current} />
      <AlertSandboxPanel open={showAlertSandbox} onClose={() => setShowAlertSandbox(false)} getBars={() => currentBarsRef.current} />
      <div className="px-4 py-1.5 border-b border-border/30 bg-secondary/20 flex gap-4 text-[10px] font-mono text-muted-foreground shrink-0">
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">O</span> <span ref={oRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">H</span> <span ref={hRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">L</span> <span ref={lRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">C</span> <span ref={cRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">V</span> <span ref={vRef} className="text-foreground font-medium tabular-nums">--</span></span>
      </div>
      <div ref={chartContainerRef} className="flex-1 relative transition-colors duration-300 overflow-hidden">
        {/* 💡 Tick 图模式：使用高频实时折线图 */}
        {selectedPeriod === 'tick' && (
          <HighFreqChartWrapper
            symbol={selectedSymbol}
            referencePrice={realQuote && hasData ? parseFloat(realQuote.last_price) : (selectedItem?.price ?? null)}
            referenceLabel={realQuote && hasData ? '现价' : '前收'}
            marketTz={/\.(HK)$|^HK\./i.test(selectedSymbol) ? 'HKT' : 'ET'}
          />
        )}
        {/* 💡 Tick 模式下父组件 crosshair 测量盒不显示(避免与子图双重叠) */}
        {selectedPeriod !== 'tick' && (
          <>
            <div ref={measureBoxRef} className="absolute pointer-events-none border border-primary/50 bg-primary/10 hidden z-10" />
            <div ref={measureInfoRef} className="absolute pointer-events-none hidden z-20 flex-col items-center justify-center bg-popover/90 backdrop-blur-sm border border-border/50 rounded shadow-lg p-1.5 text-[10px] font-mono tabular-nums whitespace-nowrap transition-none">
              <div ref={measurePriceRef} className="font-bold" />
              <div ref={measurePctRef} />
            </div>
          </>
        )}
        {showEvents && selectedPeriod !== 'tick' && stockEvents.slice(0, 3).map((ev: StockEvent, i: number) => {
          // 💡 根据事件类型和重要性设置不同颜色
          const colorMap = {
            earnings: { bg: 'bg-blue-500/20 dark:bg-blue-400/20', border: 'border-blue-500/40 dark:border-blue-400/40', text: 'text-blue-600 dark:text-blue-300', line: 'bg-blue-500/50 dark:bg-blue-400/50', dot: 'bg-blue-500 dark:bg-blue-400' },
            dividend: { bg: 'bg-green-500/20 dark:bg-green-400/20', border: 'border-green-500/40 dark:border-green-400/40', text: 'text-green-600 dark:text-green-300', line: 'bg-green-500/50 dark:bg-green-400/50', dot: 'bg-green-500 dark:bg-green-400' },
            news: { bg: 'bg-amber-500/20 dark:bg-amber-400/20', border: 'border-amber-500/40 dark:border-amber-400/40', text: 'text-amber-600 dark:text-amber-300', line: 'bg-amber-500/50 dark:bg-amber-400/50', dot: 'bg-amber-500 dark:bg-amber-400' },
          }
          const colors = colorMap[ev.type] || colorMap.news
          return (
            <div key={i} className="absolute bottom-4 flex flex-col items-center gap-0.5" style={{ left: `${20 + i * 30}%` }}>
              <span className={cn('text-[8px] font-bold px-1 py-0.5 rounded border', colors.bg, colors.border, colors.text)} title={ev.label}>
                {ev.type === 'earnings' ? '📊' : ev.type === 'dividend' ? '💰' : '📰'} {ev.label.slice(0, 15)}
              </span>
              <div className={cn('w-px h-3', colors.line)} />
              <div className={cn('h-1 w-1 rounded-full', colors.dot)} />
            </div>
          )
        })}
        {/* PROD-02: AI 图表标注徽标（点击标记或价格线后可见信号提示） */}
        {aiSymbol && aiPayload && (normalizeSymbol(aiSymbol) === normalizeSymbol(selectedSymbol)) && (
          <div className="absolute top-2 right-2 z-30 flex items-center gap-1.5 rounded-md border border-violet-500/40 bg-violet-500/10 backdrop-blur-sm px-2 py-1 text-[10px] font-mono text-violet-300 shadow-sm">
            <span className="font-semibold">🤖 AI 标注</span>
            {(aiPayload.signals?.length ?? 0) > 0 && <span className="px-1 rounded bg-violet-500/20">{aiPayload.signals!.length} 信号</span>}
            {(aiPayload.levels?.length ?? 0) > 0 && <span className="px-1 rounded bg-violet-500/20">{aiPayload.levels!.length} 价位</span>}
            {(aiPayload.zones?.length ?? 0) > 0 && <span className="px-1 rounded bg-violet-500/20">{aiPayload.zones!.length} 区域</span>}
            <button
              onClick={() => useChartAnnotationStore.getState().clear()}
              className="ml-0.5 text-violet-300/70 hover:text-violet-100 leading-none"
              title="清除 AI 标注"
            >✕</button>
          </div>
        )}
      </div>
      {showEvents && stockEvents.length > 0 && (
        <div className="border-t border-border/30 px-3 py-1.5 flex items-center gap-2 shrink-0 overflow-x-auto">
          <span className="text-[9px] font-semibold text-muted-foreground uppercase flex-shrink-0">个股事件</span>
          {stockEvents.map((ev: StockEvent) => {
            // 💡 根据事件类型设置不同颜色
            const typeColors = {
              earnings: 'bg-blue-500/10 dark:bg-blue-400/10 border-blue-500/30 dark:border-blue-400/30 text-blue-600 dark:text-blue-300',
              dividend: 'bg-green-500/10 dark:bg-green-400/10 border-green-500/30 dark:border-green-400/30 text-green-600 dark:text-green-300',
              news: 'bg-amber-500/10 dark:bg-amber-400/10 border-amber-500/30 dark:border-amber-400/30 text-amber-600 dark:text-amber-300',
            }
            const colorClass = typeColors[ev.type] || typeColors.news
            const icon = ev.type === 'earnings' ? '📊' : ev.type === 'dividend' ? '💰' : '📰'
            return (
              <span key={ev.date + ev.type} className={cn('text-[9px] px-1.5 py-0.5 rounded border font-mono flex-shrink-0', colorClass)} title={ev.label}>
                {ev.date.slice(5)} {icon} {ev.label.slice(0, 20)}
              </span>
            )
          })}
        </div>
      )}
      <OrderConfirmModal />
    </div>
  )
}
