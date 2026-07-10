import React, { useState, useEffect, useRef } from 'react'
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries, HistogramSeries, AreaSeries, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp, type IPriceLine } from 'lightweight-charts'
import { AlertTriangle, TrendingUp, TrendingDown, Eye, EyeOff, Pencil, Globe, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { MOCK_PRICE_EVENTS } from '@/services/mock'
import { useIndicatorWorker } from '@/hooks/use-indicator-worker'
import type { WatchlistItem } from '@/stores/use-watchlist'

// 💡 图表周期配置：分时图、5日图、日K图，后续可扩展周K/月K/季K/年K
const periods = [
  { id: '1m', label: '分时' },
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
}

export function LightweightChartCanvas({ selectedSymbol, selectedPeriod, setSelectedPeriod, theme, realQuote, realHistory, gatewayStatus, isWatchlistExpanded, toggleWatchlist, selectedItem, hasData }: LightweightChartCanvasProps) {
  const { toast } = useToast()
  const [showEvents, setShowEvents] = useState(true)
  const [showMA20, setShowMA20] = useState(true)
  const [showMA50, setShowMA50] = useState(true)
  const [showMA200, setShowMA200] = useState(true)
  const [showBB, setShowBB] = useState(true)
  const [showMACD, setShowMACD] = useState(true)
  const [showRSI, setShowRSI] = useState(true)
  const [showKDJ, setShowKDJ] = useState(true)
  const [isDrawMode, setIsDrawMode] = useState(false)
  const isDrawModeRef = useRef(false)
  useEffect(() => { isDrawModeRef.current = isDrawMode }, [isDrawMode])

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
  const workerRef = useIndicatorWorker()
  
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
        if (seriesRef.current && lastCandleRef.current) {
          const lastPrice = detail.last_price;
          if (!isNaN(lastPrice) && lastPrice > 0) {
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
  }, [selectedSymbol, theme]);

  useEffect(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) chartRef.current.remove()
    
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: theme === 'dark' ? '#94a3b8' : '#64748b' },
      grid: { vertLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' }, horzLines: { color: theme === 'dark' ? '#334155' : '#e2e8f0' } },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderColor: theme === 'dark' ? '#475569' : '#cbd5e1', autoScale: true, scaleMargins: { top: 0.1, bottom: 0.40 } },
      timeScale: { borderColor: theme === 'dark' ? '#475569' : '#cbd5e1', timeVisible: true, fixLeftEdge: true, fixRightEdge: true },
    })

    const bbUpperLine = chart.addSeries(AreaSeries, { lineColor: theme === 'dark' ? 'rgba(251, 191, 36, 0.4)' : 'rgba(217, 119, 6, 0.4)', topColor: theme === 'dark' ? 'rgba(251, 191, 36, 0.15)' : 'rgba(217, 119, 6, 0.15)', bottomColor: 'rgba(0, 0, 0, 0)', lineWidth: 1, lineStyle: LineStyle.Dashed, crosshairMarkerVisible: false })
    const bbLowerLine = chart.addSeries(LineSeries, { color: theme === 'dark' ? 'rgba(251, 191, 36, 0.4)' : 'rgba(217, 119, 6, 0.4)', lineWidth: 1, lineStyle: LineStyle.Dashed, crosshairMarkerVisible: false })
    const candlestickSeries = chart.addSeries(CandlestickSeries, { upColor: theme === 'dark' ? '#10b981' : '#059669', downColor: theme === 'dark' ? '#ef4444' : '#dc2626', borderVisible: false, wickUpColor: theme === 'dark' ? '#10b981' : '#059669', wickDownColor: theme === 'dark' ? '#ef4444' : '#dc2626' })
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

    const handleResize = (entries: ResizeObserverEntry[]) => {
      if (entries.length === 0 || !chartRef.current) return
      const newRect = entries[0].contentRect
      requestAnimationFrame(() => {
        if (chartRef.current) {
          chartRef.current.applyOptions({ width: newRect.width, height: newRect.height })
          if (dataLengthRef.current > 0) chartRef.current.timeScale().applyOptions({ minBarSpacing: Math.max(0.1, newRect.width / dataLengthRef.current) })
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
      if (isValid) {
        const cData = param.seriesData.get(candlestickSeries) as any; const vData = param.seriesData.get(volumeSeries) as any;
        if (cData && updateOhlcvDomRef.current) updateOhlcvDomRef.current({ ...cData, volume: vData?.value || 0 });
      } else {
        if (lastCandleRef.current && updateOhlcvDomRef.current) updateOhlcvDomRef.current(lastCandleRef.current);
      }
    });

    chart.subscribeClick((param) => {
      if (param.time && markersRef.current) {
        const clickedMarker = markersRef.current.find(m => m.time === param.time)
        if (clickedMarker && clickedMarker.detail) toast({ title: `📊 信号触发 (${new Date((param.time as number) * 1000).toLocaleString('zh-CN', { hour12: false })})`, description: clickedMarker.detail })
      }
      if (!isDrawModeRef.current || !param.point || !param.time) return;
      const price = candlestickSeries.coordinateToPrice(param.point.y);
      if (price === null) return;
      const container = chartContainerRef.current as any;
      if (!container._activeDrawingPlugin) {
        const pluginColor = theme === 'dark' ? '#38bdf8' : '#0284c7';
        container._activeDrawingPlugin = new TrendLinePrimitive(chart, candlestickSeries, param.time, price, pluginColor);
        candlestickSeries.attachPrimitive(container._activeDrawingPlugin);
      } else {
        container._activeDrawingPlugin.updateEndPoint(param.time, price);
        container._activeDrawingPlugin = null; setIsDrawMode(false);
      }
    });
    
    const handleMouseDown = (e: MouseEvent) => {
      if (e.shiftKey && currentCrosshairRef.current) {
        container._isMeasuring = true; container._measureStart = currentCrosshairRef.current;
        if (measureBoxRef.current) measureBoxRef.current.style.display = 'block';
        if (measureInfoRef.current) measureInfoRef.current.style.display = 'flex';
        updateMeasureDOM(container._measureStart, currentCrosshairRef.current);
      } else {
        if (measureBoxRef.current) measureBoxRef.current.style.display = 'none';
        if (measureInfoRef.current) measureInfoRef.current.style.display = 'none';
        container._isMeasuring = false;
      }
    };
    const handleMouseUp = () => { if (container._isMeasuring) container._isMeasuring = false; };
    container.addEventListener('mousedown', handleMouseDown); window.addEventListener('mouseup', handleMouseUp);

    return () => {
      ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; volumeRef.current = null; macdDiffRef.current = null; macdDeaRef.current = null; macdHistRef.current = null; rsiLineRef.current = null; rsiHistRef.current = null; kdjKRef.current = null; kdjDRef.current = null; kdjJRef.current = null; bbUpperRef.current = null; bbLowerRef.current = null; container.removeEventListener('mousedown', handleMouseDown); window.removeEventListener('mouseup', handleMouseUp);
    }
  }, [theme])

  useEffect(() => {
    if (!seriesRef.current) return
    if (!realHistory.length) {
      seriesRef.current.setData([]); if (ma20Ref.current) ma20Ref.current.setData([]); if (ma50Ref.current) ma50Ref.current.setData([]); if (ma200Ref.current) ma200Ref.current.setData([]); if (bbUpperRef.current) bbUpperRef.current.setData([]); if (bbLowerRef.current) bbLowerRef.current.setData([]); if (volumeRef.current) volumeRef.current.setData([]); if (macdDiffRef.current) macdDiffRef.current.setData([]); if (macdDeaRef.current) macdDeaRef.current.setData([]); if (macdHistRef.current) macdHistRef.current.setData([]); if (rsiLineRef.current) rsiLineRef.current.setData([]); if (rsiHistRef.current) rsiHistRef.current.setData([]); if (kdjKRef.current) kdjKRef.current.setData([]); if (kdjDRef.current) kdjDRef.current.setData([]); if (kdjJRef.current) kdjJRef.current.setData([]);
      if (oRef.current) oRef.current.textContent = '--'; if (hRef.current) hRef.current.textContent = '--'; if (lRef.current) lRef.current.textContent = '--'; if (cRef.current) cRef.current.textContent = '--'; if (vRef.current) vRef.current.textContent = '--'; lastCandleRef.current = null; return
    }
    
    const sortedHistory = [...realHistory].sort((a, b) => new Date(a.time.replace(/-/g, '/')).getTime() - new Date(b.time.replace(/-/g, '/')).getTime())
    if (!workerRef.current) return
    const reqId = Date.now() + Math.random()
    
    workerRef.current.onmessage = (e: any) => {
      if (e.data.id !== reqId) return
      const { ma20, ma50, ma200, bb, macdCalc, rsiCalc, kdjCalc } = e.data
      const markers: any[] = []
      const lwData = sortedHistory.map((k, i) => {
        const timestamp = new Date(k.time.replace(/-/g, '/')).getTime() / 1000
        const point: any = { time: timestamp as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close, volume: k.volume }
        if (i >= 5 && rsiCalc[i] !== '-' && rsiCalc[i-1] !== '-' && kdjCalc.k[i] !== '-' && kdjCalc.k[i-1] !== '-') {
          const currClose = k.close; const prevClose = sortedHistory[i-1].close; const minClose5 = Math.min(...sortedHistory.slice(i-5, i).map(x => x.close)); const maxClose5 = Math.max(...sortedHistory.slice(i-5, i).map(x => x.close)); const currRsi = Number(rsiCalc[i]); const prevRsi = Number(rsiCalc[i-1]); const currMacdHist = Number(macdCalc.macd[i]); const prevMacdHist = Number(macdCalc.macd[i-1]); const currK = Number(kdjCalc.k[i]); const prevK = Number(kdjCalc.k[i-1]); const currD = Number(kdjCalc.d[i]); const prevD = Number(kdjCalc.d[i-1]);
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
      if (ma20Ref.current) ma20Ref.current.setData(ma20Data); if (ma50Ref.current) ma50Ref.current.setData(ma50Data); if (ma200Ref.current) ma200Ref.current.setData(ma200Data); if (bbUpperRef.current) bbUpperRef.current.setData(bbUpperData); if (bbLowerRef.current) bbLowerRef.current.setData(bbLowerData); if (volumeRef.current) volumeRef.current.setData(volumeData); if (macdDiffRef.current) macdDiffRef.current.setData(macdDiffData); if (macdDeaRef.current) macdDeaRef.current.setData(macdDeaData); if (macdHistRef.current) macdHistRef.current.setData(macdHistData); if (rsiLineRef.current) rsiLineRef.current.setData(rsiData); if (rsiHistRef.current) rsiHistRef.current.setData(rsiHistData); if (kdjKRef.current) kdjKRef.current.setData(kdjKData); if (kdjDRef.current) kdjDRef.current.setData(kdjDData); if (kdjJRef.current) kdjJRef.current.setData(kdjJData);
      if (!isFirstLoadFittedRef.current && chartRef.current && lwData.length > 0) { requestAnimationFrame(() => { chartRef.current?.timeScale().fitContent() }); isFirstLoadFittedRef.current = true; }
      dataLengthRef.current = lwData.length;
      if (chartContainerRef.current && chartRef.current && lwData.length > 0) chartRef.current.timeScale().applyOptions({ minBarSpacing: Math.max(0.1, chartContainerRef.current.clientWidth / lwData.length) });
      if (lwData.length > 0) {
        lastCandleRef.current = { ...lwData[lwData.length - 1] }
        if (currentPriceLineRef.current) currentPriceLineRef.current.applyOptions({ price: lwData[lwData.length - 1].close })
        if (updateOhlcvDomRef.current && !isCrosshairActiveRef.current) updateOhlcvDomRef.current(lastCandleRef.current)
      }
    }
    workerRef.current.postMessage({ id: reqId, history: sortedHistory, params: { maPeriods: [20, 50, 200], bbParams: [20, 2], macdParams: [12, 26, 9], rsiPeriod: 14, kdjParams: [9, 3, 3] } })
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
          <button onClick={() => setShowRSI(!showRSI)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showRSI ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="RSI (相对强弱指数)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#8b5cf6]", !showRSI && "opacity-50")} />RSI</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="KDJ开关">
          <button onClick={() => setShowKDJ(!showKDJ)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium flex items-center gap-1', showKDJ ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} title="KDJ (随机指标)"><span className={cn("h-1.5 w-1.5 rounded-full bg-[#f472b6]", !showKDJ && "opacity-50")} />KDJ</button>
        </div>
        <div className="flex items-center gap-0.5 bg-background border border-border/50 p-0.5 rounded-md shadow-sm" role="group" aria-label="K线周期">
          {periods.map((p, idx) => (<button key={p.id} onClick={() => setSelectedPeriod(p.id)} className={cn('px-2 py-0.5 rounded text-[10px] font-mono transition-colors font-medium', selectedPeriod === p.id ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground')} aria-pressed={selectedPeriod === p.id} title={`切换至${p.label}周期 (快捷键: ${idx + 1})`}>{p.label}</button>))}
        </div>
        <Button variant={isDrawMode ? "default" : "outline"} size="sm" onClick={() => setIsDrawMode(!isDrawMode)} className={cn("h-7 px-2.5 gap-1.5 text-[10px]", isDrawMode ? "bg-primary text-primary-foreground shadow-sm shadow-primary/30" : "border-border/50 bg-background")} title={isDrawMode ? '取消画线 (点击两点连线)' : '自由画线 (趋势线)'}><Pencil className="h-3.5 w-3.5" /></Button>
        <Button variant="outline" size="sm" onClick={() => setShowEvents(!showEvents)} className="h-7 px-2.5 gap-1.5 text-[10px] border-border/50 bg-background" title={showEvents ? '隐藏事件' : '显示事件'}>{showEvents ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}</Button>
      </div>
      <div className="px-4 py-1.5 border-b border-border/30 bg-secondary/20 flex gap-4 text-[10px] font-mono text-muted-foreground shrink-0">
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">O</span> <span ref={oRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">H</span> <span ref={hRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">L</span> <span ref={lRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">C</span> <span ref={cRef} className="text-foreground font-medium tabular-nums">--</span></span>
        <span className="flex items-center gap-1.5"><span className="font-semibold opacity-50">V</span> <span ref={vRef} className="text-foreground font-medium tabular-nums">--</span></span>
      </div>
      <div ref={chartContainerRef} className="flex-1 relative transition-colors duration-300 overflow-hidden">
        <div ref={measureBoxRef} className="absolute pointer-events-none border border-primary/50 bg-primary/10 hidden z-10" />
        <div ref={measureInfoRef} className="absolute pointer-events-none hidden z-20 flex-col items-center justify-center bg-popover/90 backdrop-blur-sm border border-border/50 rounded shadow-lg p-1.5 text-[10px] font-mono tabular-nums whitespace-nowrap transition-none">
          <div ref={measurePriceRef} className="font-bold" />
          <div ref={measurePctRef} />
        </div>
        {showEvents && MOCK_PRICE_EVENTS.slice(0,2).map((ev, i) => (
          <div key={i} className="absolute bottom-4 flex flex-col items-center gap-0.5" style={{ left: `${25 + i * 35}%` }}>
            <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-red-500/20 dark:bg-red-400/20 border border-red-500/40 dark:border-red-400/40 text-red-600 dark:text-red-300">{ev.label}</span>
            <div className="w-px h-3 bg-red-500/50 dark:bg-red-400/50" /><div className="h-1 w-1 rounded-full bg-red-500 dark:bg-red-400" />
          </div>
        ))}
      </div>
      {showEvents && (
        <div className="border-t border-border/30 px-3 py-1.5 flex items-center gap-2 shrink-0">
          <span className="text-[9px] font-semibold text-muted-foreground uppercase">事件</span>
          {MOCK_PRICE_EVENTS.map((ev) => (<span key={ev.date} className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 dark:bg-red-400/10 border border-red-500/30 dark:border-red-400/30 text-red-600 dark:text-red-300 font-mono">{ev.date} {ev.label}</span>))}
        </div>
      )}
    </div>
  )
}