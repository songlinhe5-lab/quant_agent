"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import * as echarts from "echarts"

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface TimeBucket {
  bucket: number
  time_range: string
  qty: number
  avg_price: number
  pct_of_total: number
}

interface QualityMetrics {
  slippage_bps: number
  vwap_deviation_bps: number
  implementation_shortfall_bps: number
  participation_rate: number
}

interface ExecutionSummary {
  target_qty: number
  filled_qty: number
  completion_pct: number
  actual_avg_price: number
  benchmark_price: number
  total_cost: number
}

interface ExecutionReport {
  algo_id: string
  algo_type: string
  symbol: string
  side: string
  summary: ExecutionSummary
  quality_metrics: QualityMetrics
  time_distribution: TimeBucket[]
  assessment: "EXCELLENT" | "GOOD" | "ACCEPTABLE" | "POOR"
}

interface AlgoAnalyticsPanelProps {
  algoId?: string
  algoType?: string
  symbol?: string
  side?: string
  filledQty?: number
  totalCost?: number
  targetQty?: number
  durationMinutes?: number
}

// ── API ───────────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// ── 组件 ─────────────────────────────────────────────────────────────────────

export function AlgoAnalyticsPanel({
  algoId = "",
  algoType = "TWAP",
  symbol = "US.AAPL",
  side = "BUY",
  filledQty = 0,
  totalCost = 0,
  targetQty = 0,
  durationMinutes = 60,
}: AlgoAnalyticsPanelProps) {
  const [benchmarkPrice, setBenchmarkPrice] = useState("150")
  const [marketVwap, setMarketVwap] = useState("150")
  const [marketVolume, setMarketVolume] = useState("100000")
  const [report, setReport] = useState<ExecutionReport | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const timeChartRef = useRef<HTMLDivElement>(null)
  const timeChartInstance = useRef<echarts.ECharts | null>(null)

  async function loadAnalytics() {
    if (!algoId.trim()) return
    setIsLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/oms/algo/analytics/${encodeURIComponent(algoId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          benchmark_price: parseFloat(benchmarkPrice),
          market_volume: parseInt(marketVolume),
          market_vwap: parseFloat(marketVwap),
          fills: [],
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setReport(json.data)
    } catch (e: any) {
      setError(e.message ?? "分析失败")
    } finally {
      setIsLoading(false)
    }
  }

  // ── 时间分布图 ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!timeChartRef.current || !report?.time_distribution?.length) return
    if (!timeChartInstance.current) {
      timeChartInstance.current = echarts.init(timeChartRef.current)
    }
    const chart = timeChartInstance.current
    const buckets = report.time_distribution
    const labels = buckets.map((b) => b.time_range)
    const quantities = buckets.map((b) => b.qty)
    const avgPrices = buckets.map((b) => b.avg_price)

    const isDark = true
    const option = {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: {
        data: ["成交量", "均价"],
        textStyle: { color: "#94a3b8", fontSize: 11 },
        top: 0,
      },
      grid: { top: 30, right: 60, bottom: 30, left: 50 },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      },
      yAxis: [
        {
          type: "value",
          name: "成交量",
          axisLabel: { color: "#94a3b8", fontSize: 10 },
          splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)", type: "dashed" } },
        },
        {
          type: "value",
          name: "均价",
          position: "right",
          axisLabel: { color: "#94a3b8", fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "成交量",
          type: "bar",
          data: quantities,
          itemStyle: {
            color: report.side === "BUY" ? "rgba(52,211,153,0.6)" : "rgba(248,113,113,0.6)",
          },
          barMaxWidth: 28,
        },
        {
          name: "均价",
          type: "line",
          yAxisIndex: 1,
          data: avgPrices,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#a78bfa", width: 2 },
          itemStyle: { color: "#a78bfa" },
        },
      ],
    }
    chart.setOption(option, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [report])

  // ── 指标卡片数据 ────────────────────────────────────────────────────────────

  const metrics = report?.quality_metrics
  const summary = report?.summary
  const assessmentColor = {
    EXCELLENT: "text-emerald-400 border-emerald-400",
    GOOD: "text-blue-400 border-blue-400",
    ACCEPTABLE: "text-amber-400 border-amber-400",
    POOR: "text-red-400 border-red-400",
  }
  const assessmentLabel = {
    EXCELLENT: "执行优秀",
    GOOD: "执行良好",
    ACCEPTABLE: "可接受",
    POOR: "执行较差",
  }

  return (
    <div className="space-y-4 p-4">
      {/* 标题 */}
      <div className="glass-card rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="font-semibold text-sm">算法执行分析</h3>
          <Badge variant="outline" className="text-[10px]">TRADE-02</Badge>
          {report && (
            <Badge variant="outline" className={cn("text-[10px]", assessmentColor[report.assessment])}>
              {assessmentLabel[report.assessment] ?? report.assessment}
            </Badge>
          )}
        </div>

        {/* 参数输入 */}
        <div className="flex items-end gap-3 flex-wrap">
          <div className="w-36">
            <label className="text-xs text-muted-foreground mb-1 block">算法 ID</label>
            <Input
              value={algoId}
              onChange={() => {}}
              placeholder="algo_twap_xxx"
              className="font-mono bg-input border-border text-xs"
              readOnly
            />
          </div>
          <div className="w-28">
            <label className="text-xs text-muted-foreground mb-1 block">基准价格</label>
            <Input
              type="number"
              value={benchmarkPrice}
              onChange={(e) => setBenchmarkPrice(e.target.value)}
              className="font-mono bg-input border-border text-xs"
            />
          </div>
          <div className="w-28">
            <label className="text-xs text-muted-foreground mb-1 block">市场 VWAP</label>
            <Input
              type="number"
              value={marketVwap}
              onChange={(e) => setMarketVwap(e.target.value)}
              className="font-mono bg-input border-border text-xs"
            />
          </div>
          <div className="w-32">
            <label className="text-xs text-muted-foreground mb-1 block">市场成交量</label>
            <Input
              type="number"
              value={marketVolume}
              onChange={(e) => setMarketVolume(e.target.value)}
              className="font-mono bg-input border-border text-xs"
            />
          </div>
          <Button
            onClick={loadAnalytics}
            disabled={isLoading || !algoId.trim()}
            className="bg-violet-500 hover:bg-violet-600 text-white text-xs"
          >
            {isLoading ? "分析中..." : "生成报告"}
          </Button>
          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full glass-card rounded-lg" />
          ))}
        </div>
      )}

      {/* 指标卡片 */}
      {report && metrics && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <MetricCard
            label="执行滑点"
            value={`${metrics.slippage_bps > 0 ? "+" : ""}${metrics.slippage_bps.toFixed(2)}`}
            unit="bps"
            color={metrics.slippage_bps > 0 ? "emerald" : metrics.slippage_bps > -5 ? "amber" : "red"}
            description="vs 基准价格"
          />
          <MetricCard
            label="VWAP 偏离"
            value={`${metrics.vwap_deviation_bps > 0 ? "+" : ""}${metrics.vwap_deviation_bps.toFixed(2)}`}
            unit="bps"
            color={metrics.vwap_deviation_bps > 0 ? "emerald" : "red"}
            description="vs 市场 VWAP"
          />
          <MetricCard
            label="执行缺口 (IS)"
            value={`${metrics.implementation_shortfall_bps.toFixed(2)}`}
            unit="bps"
            color={metrics.implementation_shortfall_bps < 0 ? "emerald" : "red"}
            description="实际 vs 纸面"
          />
          <MetricCard
            label="市场参与率"
            value={`${metrics.participation_rate.toFixed(2)}`}
            unit="%"
            color={metrics.participation_rate < 10 ? "emerald" : "amber"}
            description="占市场总量比"
          />
        </div>
      )}

      {/* 执行摘要 + 时间分布图 */}
      {report && summary && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* 摘要卡 */}
          <div className="glass-card rounded-lg p-4">
            <h4 className="text-xs text-muted-foreground mb-3">执行摘要</h4>
            <div className="space-y-2 text-xs">
              <Row label="算法类型" value={report.algo_type} />
              <Row label="标的" value={report.symbol} />
              <Row label="方向" value={report.side} mono color={report.side === "BUY" ? "emerald" : "red"} />
              <Row
                label="完成率"
                value={`${summary.completion_pct.toFixed(1)}%`}
                color={summary.completion_pct >= 100 ? "emerald" : "amber"}
              />
              <Row label="目标数量" value={summary.target_qty.toLocaleString()} mono />
              <Row label="已成交" value={summary.filled_qty.toLocaleString()} mono />
              <Row label="实际均价" value={summary.actual_avg_price.toFixed(2)} mono />
              <Row label="基准价格" value={summary.benchmark_price.toFixed(2)} mono muted />
              <Row label="总成本" value={`$${summary.total_cost.toLocaleString()}`} mono />
            </div>
          </div>

          {/* 时间分布图 */}
          <div className="glass-card rounded-lg p-4 lg:col-span-2">
            <h4 className="text-xs text-muted-foreground mb-2">执行时间分布</h4>
            <div ref={timeChartRef} className="w-full h-52" />
          </div>
        </div>
      )}

      {!report && !isLoading && (
        <div className="glass-card rounded-lg p-8 text-center text-sm text-muted-foreground">
          输入算法 ID 和基准价格，点击「生成报告」查看执行分析
        </div>
      )}
    </div>
  )
}

// ── 辅助组件 ─────────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  unit,
  color,
  description,
}: {
  label: string
  value: string
  unit: string
  color: "emerald" | "red" | "amber" | "blue"
  description: string
}) {
  const colorMap = {
    emerald: "text-emerald-400",
    red: "text-red-400",
    amber: "text-amber-400",
    blue: "text-blue-400",
  }
  return (
    <div className="glass-card rounded-lg p-3 flex flex-col gap-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-1">
        <span className={cn("font-mono text-lg font-semibold", colorMap[color])}>{value}</span>
        <span className="text-xs text-muted-foreground">{unit}</span>
      </div>
      <span className="text-[10px] text-muted-foreground">{description}</span>
    </div>
  )
}

function Row({
  label,
  value,
  mono,
  color,
  muted,
}: {
  label: string
  value: string
  mono?: boolean
  color?: "emerald" | "red" | "amber"
  muted?: boolean
}) {
  const colorMap = { emerald: "text-emerald-400", red: "text-red-400", amber: "text-amber-400" }
  return (
    <div className="flex justify-between items-center">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn(
          mono && "font-mono",
          color ? colorMap[color] : muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  )
}
