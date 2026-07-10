'use client'

import { useEffect, useRef } from 'react'
import { Application, Container, Graphics, Text, TextStyle } from 'pixi.js'
import { Zap } from 'lucide-react'
import { cn } from '@/lib/utils'

interface OrderBookRowProps {
  priceText: Text
  sizeText: Text
  depthBar: Graphics
  flashOverlay: Graphics
  flashAlpha: number
  lastSize: number
}

export function OrderBookWebGL({ symbol, theme, hideHeader = false }: { symbol: string; theme?: string; hideHeader?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const appRef = useRef<Application | null>(null)
  
  // 维护对象池，避免在渲染循环中创建任何新对象 (Zero-GC)
  const askRows = useRef<OrderBookRowProps[]>([])
  const bidRows = useRef<OrderBookRowProps[]>([])
  const closedTextRef = useRef<Text | null>(null)
  const zoomLevelRef = useRef<number>(1.0)

  useEffect(() => {
    if (!containerRef.current) return
    let isMounted = true
    let resizeObserver: ResizeObserver | null = null
    let handleWheel: ((e: WheelEvent) => void) | null = null

    const initPixi = async () => {
      // 1. 初始化 PixiJS (WebGL)
      const app = new Application()
      await app.init({
        resizeTo: containerRef.current!,
        backgroundAlpha: 0, // 透明背景，融入 Tailwind 暗黑卡片
        antialias: true,
        resolution: window.devicePixelRatio || 1,
      })
      
      if (!isMounted || !containerRef.current) {
        app.destroy(true)
        return
      }

      appRef.current = app
      containerRef.current.appendChild(app.canvas)

      // 引入主容器实现镜头居中与缩放
      const mainContainer = new Container()
      app.stage.addChild(mainContainer)

      // 2. 预设排版常量与文字样式
      const ROW_HEIGHT = 22
      const MAX_ROWS = 40 // 💡 扩大上限至 40 档，以支持滚轮缩放查看极深盘口
      const WIDTH = app.screen.width

      const textStyle = new TextStyle({
        fontFamily: 'monospace', // 等宽字体防止跳动
        fontSize: 12,
        fill: theme === 'dark' ? '#94a3b8' : '#64748b', // 适配主题色
        fontWeight: 'bold',
      })

      // 初始化 10 档卖盘 (Asks) 和 10 档买盘 (Bids)
      const createRow = (yPos: number, isAsk: boolean): OrderBookRowProps => {
        const rowContainer = new Container()
        rowContainer.y = yPos

        // 深度条 (背景面积)
        const depthBar = new Graphics()
        depthBar.rect(0, 0, 1, ROW_HEIGHT).fill(isAsk ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)')
        depthBar.x = WIDTH // 初始在最右侧，向左延伸
        rowContainer.addChild(depthBar)

        // 闪烁层 (Flash-bang)
        const flashOverlay = new Graphics()
        flashOverlay.rect(0, 0, 1, ROW_HEIGHT).fill(isAsk ? 'rgba(239, 68, 68, 0.5)' : 'rgba(16, 185, 129, 0.5)')
        flashOverlay.alpha = 0
        flashOverlay.width = WIDTH
        rowContainer.addChild(flashOverlay)

        // 价格文本
        const priceText = new Text({ text: '---', style: { ...textStyle, fill: isAsk ? '#ef4444' : '#10b981' } })
        priceText.x = 10
        priceText.y = 4
        rowContainer.addChild(priceText)

        // 数量文本
        const sizeText = new Text({ text: '---', style: textStyle })
        sizeText.x = WIDTH - 10
        sizeText.anchor.set(1, 0) // 右对齐
        sizeText.y = 4
        rowContainer.addChild(sizeText)

        mainContainer.addChild(rowContainer)

        return { priceText, sizeText, depthBar, flashOverlay, flashAlpha: 0, lastSize: 0 }
      }

      // 💡 修复：确保在初始化前清空对象池。
      // 否则在 React Strict Mode 的双重挂载机制下，数组会累积上次被销毁的幽灵对象
      askRows.current = []
      bidRows.current = []

      // Spread 间隔占位 (如需要可在坐标上+10)
      const SPREAD_GAP = 10

      // 生成卖盘 (Asks) - 从中心向上延伸
      for (let i = 0; i < MAX_ROWS; i++) {
        const yPos = -SPREAD_GAP / 2 - (i + 1) * ROW_HEIGHT
        askRows.current.push(createRow(yPos, true))
      }

      // 生成买盘 (Bids) - 从中心向下延伸
      for (let i = 0; i < MAX_ROWS; i++) {
        const yPos = SPREAD_GAP / 2 + i * ROW_HEIGHT
        bidRows.current.push(createRow(yPos, false))
      }

      // 5. 创建“市场休市”占位提示文本
      const closedText = new Text({
        text: '市场休市\nMARKET CLOSED',
        style: new TextStyle({
          fontFamily: 'monospace',
          fontSize: 16,
          fill: theme === 'dark' ? '#475569' : '#94a3b8', // slate-600 / slate-400
          fontWeight: 'bold',
          align: 'center',
        })
      })
      closedText.anchor.set(0.5) // 中心锚点
      closedText.visible = true  // 初始可见，直到收到真实的盘口数据
      app.stage.addChild(closedText)
      closedTextRef.current = closedText

      // 3. 独立的高性能动画循环 (处理闪烁衰减)
      app.ticker.add(() => {
        const decayRate = 0.05 // 闪烁消退速度
        const allRows = [...askRows.current, ...bidRows.current]
        
        for (let i = 0; i < allRows.length; i++) {
          const row = allRows[i]
          if (row.flashAlpha > 0) {
            row.flashAlpha = Math.max(0, row.flashAlpha - decayRate)
            row.flashOverlay.alpha = row.flashAlpha
          }
        }
      })

      // 4. 监听容器 Resize，自适应更新内部渲染对象的坐标与宽度
      resizeObserver = new ResizeObserver((entries) => {
        if (!isMounted || !appRef.current) return
        const newWidth = entries[0].contentRect.width
        const newHeight = entries[0].contentRect.height
        const zoom = zoomLevelRef.current
        const virtualWidth = newWidth / zoom
        
        // 永远保持 Spread 价差区间在视觉正中心
        mainContainer.y = newHeight / 2
        
        const allRows = [...askRows.current, ...bidRows.current]
        
        for (let i = 0; i < allRows.length; i++) {
          const row = allRows[i]
          // 抵消缩放造成的 X 轴横向拉伸，确保挂单量始终精准贴靠右侧边缘
          row.sizeText.x = virtualWidth - (10 / zoom)
          row.flashOverlay.width = virtualWidth
          row.depthBar.x = virtualWidth - row.depthBar.width
        }
        
        if (closedTextRef.current) {
          closedTextRef.current.x = newWidth / 2
          closedTextRef.current.y = newHeight / 2
        }
      })
      resizeObserver.observe(containerRef.current)

      // 6. 监听鼠标滚轮，实现原生级无损缩放
      handleWheel = (e: WheelEvent) => {
        e.preventDefault()
        if (!appRef.current) return
        // 向下滚缩小看更深，向上滚放大
        const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1
        const newZoom = Math.max(0.3, Math.min(1.5, zoomLevelRef.current * zoomFactor))
        zoomLevelRef.current = newZoom
        mainContainer.scale.set(newZoom)
        
        const newWidth = appRef.current.screen.width
        const virtualWidth = newWidth / newZoom
        
        const allRows = [...askRows.current, ...bidRows.current]
        for (let i = 0; i < allRows.length; i++) {
          const row = allRows[i]
          row.sizeText.x = virtualWidth - (10 / newZoom)
          row.flashOverlay.width = virtualWidth
          row.depthBar.x = virtualWidth - row.depthBar.width
        }
      }
      containerRef.current.addEventListener('wheel', handleWheel, { passive: false })
    }

    initPixi()

    // 4. 原生事件监听：绕过 React，直接变更 WebGL 内存对象
    const handleTick = (e: Event) => {
      const data = (e as CustomEvent).detail
      // 💡 修复：标准化 ticker 格式进行匹配（后端可能是 HK.00700，前端可能是 00700 或 00700.HK）
      const cleanTicker = (s: string) => s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')
      if (cleanTicker(data.ticker) !== cleanTicker(symbol) || !appRef.current) return

      const isClosed = (!data.asks || data.asks.length === 0) && (!data.bids || data.bids.length === 0)
      
      if (closedTextRef.current) {
        closedTextRef.current.visible = isClosed
      }

      if (isClosed) {
        // 市场休市时，清空当前所有的盘口显示，防止滞留旧数据
        const allRows = [...askRows.current, ...bidRows.current]
        for (let i = 0; i < allRows.length; i++) {
          const row = allRows[i]
          row.priceText.text = '---'
          row.sizeText.text = '---'
          row.depthBar.width = 0
          row.flashAlpha = 0
          row.lastSize = 0
        }
        return
      }

      // 计算全盘最大挂单量，用于深度条的动态比例渲染
      let maxVol = 100
      if (data.asks && data.bids) {
          const allSizes = [...data.asks, ...data.bids].map(x => x.size !== undefined ? Number(x.size) : Number(x.volume || 0))
          if (allSizes.length > 0) {
              maxVol = Math.max(...allSizes, 100) // 兜底至少为 100
          }
      }

      const virtualWidth = appRef.current!.screen.width / zoomLevelRef.current

      // 更新卖盘 (Asks) - 从中心向外扩散
      if (data.asks) {
        const asks = data.asks // 💡 无需 reverse! 因为 askRows[0] 就在坐标轴中心点
        for (let i = 0; i < askRows.current.length; i++) {
          const row = askRows.current[i]
          if (i < asks.length) {
            const ask = asks[i]
            const askSize = ask.size !== undefined ? Number(ask.size) : Number(ask.volume || 0)
            
            row.priceText.text = parseFloat(ask.price).toFixed(2)
            row.sizeText.text = askSize.toString()
            
            if (askSize > row.lastSize) row.flashAlpha = 0.8
            row.lastSize = askSize

            const depthWidth = Math.min((askSize / maxVol) * virtualWidth, virtualWidth)
            row.depthBar.width = depthWidth
            row.depthBar.x = virtualWidth - depthWidth // 抵消缩放拉伸，永远靠右锚定
          } else {
            // 清理不在深度范围内多余的老数据
            row.priceText.text = '---'
            row.sizeText.text = '---'
            row.depthBar.width = 0
            row.lastSize = 0
          }
        }
      }
      
      // 更新买盘 (Bids) - 从中心向外扩散
      if (data.bids) {
        const bids = data.bids
        for (let i = 0; i < bidRows.current.length; i++) {
          const row = bidRows.current[i]
          if (i < bids.length) {
            const bid = bids[i]
            const bidSize = bid.size !== undefined ? Number(bid.size) : Number(bid.volume || 0)
            
            row.priceText.text = parseFloat(bid.price).toFixed(2)
            row.sizeText.text = bidSize.toString()
            
            if (bidSize > row.lastSize) row.flashAlpha = 0.8
            row.lastSize = bidSize

            const depthWidth = Math.min((bidSize / maxVol) * virtualWidth, virtualWidth)
            row.depthBar.width = depthWidth
            row.depthBar.x = virtualWidth - depthWidth
          } else {
            row.priceText.text = '---'
            row.sizeText.text = '---'
            row.depthBar.width = 0
            row.lastSize = 0
          }
        }
      }
    }

    window.addEventListener('market_tick', handleTick)

    // 清理钩子
    return () => {
      isMounted = false
      window.removeEventListener('market_tick', handleTick)
      if (resizeObserver) resizeObserver.disconnect()
      if (containerRef.current && handleWheel) {
        containerRef.current.removeEventListener('wheel', handleWheel)
      }
      if (appRef.current) {
        appRef.current.destroy(true, { children: true, texture: true })
        appRef.current = null
      }
      askRows.current = []
      bidRows.current = []
      closedTextRef.current = null
    }
  }, [symbol, theme]) // 将 theme 加入依赖项，主题切换时重建 Canvas 刷新颜色

  return (
    <div className={cn("flex flex-col w-full h-full bg-card backdrop-blur-md shadow-sm", !hideHeader && "border border-border/40 rounded-xl overflow-hidden")}>
       {!hideHeader && (
         <div className="px-3 py-2.5 border-b border-border/40 flex justify-between bg-secondary/20 text-[10px] text-muted-foreground uppercase font-semibold">
           <span className="flex items-center gap-1.5"><Zap className="w-3 h-3 text-amber-500" /> Level 2 DOM</span>
           <span className="font-mono text-muted-foreground/80">{symbol}</span>
         </div>
       )}
       {/* WebGL Canvas 挂载点，必须设置 suppressHydrationWarning */}
       <div ref={containerRef} className="flex-1 w-full min-h-[300px] relative" suppressHydrationWarning />
    </div>
  )
}