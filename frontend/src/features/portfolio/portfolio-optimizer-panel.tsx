"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import * as echarts from "echarts"

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface OptimizationWeights {
  [symbol: string]: number
}

interface RiskContributions {
  [symbol: string]: number
}

interface OptimizationResult {
  weights: OptimizationWeights
  expected_return: number
  expected_volatility: number
  sharpe_ratio: number
  risk_contributions: RiskContributions
  effective_n: number
}

interface ModelEntry {
  name: string
  weights: OptimizationWeights
  expected_return: number
  expected_volatility: number
  sharpe_ratio: number
  risk_contributions: RiskContributions
  effective_n: number
}

interface FrontierPoint {
  expected_return: number
  expected_volatility: number
  sharpe_ratio: number
  weights: OptimizationWeights
}

interface CompareData {
  models: ModelEntry[]
  best_model: string
}

// ── API ───────────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, options)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.data ?? json
}

// ── 常量 ─────────────────────────────────────────────────────────────────────

const MODEL_OPTIONS = [
  { value: "equal_weight", label: "等权", color: "#94a3b8" },
  { value: "markowitz", label: "Markowitz", color: "#34d399" },
  { value: "risk_parity", label: "风险平价", color: "#a78bfa" },
  { value: "max_sharpe", label: "Max Sharpe", color: "#fbbf24" },
]

const MODEL_LABEL: Record<string, string> = {
  equal_weight: "等权",
  markowitz: "Markowitz",
  risk_parity: "风险平价",
  max_sharpe: "Max Sharpe",
}

// ── 组件 ─────────────────────────────────────────────────────────────────────

export function PortfolioOptimizerPanel() {
  const [symbolsInput, setSymbolsInput] = useState("US.AAPL,US.MSFT,US.NVDA,US.GOOG,US.AMZN")
  const [model, setModel] = useState("markowitz")
  const [maxWeight, setMaxWeight] = useState([30])
  const [riskFreeRate, setRiskFreeRate] = useState("0.02")
  const [period, setPeriod] = useState("1y")

  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [compareData, setCompareData] = useState<CompareData | null>(null)
  const [frontier, setFrontier] = useState<FrontierPoint[] | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pieChartRef = useRef<HTMLDivElement>(null)
  const riskChartRef = useRef<HTMLDivElement>(null)
  const frontierChartRef = useRef<HTMLDivElement>(null)
  const pieChartInstance = useRef<echarts.ECharts | null>(null)
  const riskChartInstance = useRef<echarts.ECharts | null>(null)
  const frontierChartInstance = useRef<echarts.ECharts | null>(null)

  const symbols = symbolsInput.split(",").map((s) => s.trim()).filter(Boolean)

  // ── 优化请求 ────────────────────────────────────────────────────────────────

  async function runOptimize() {
    if (symbols.length < 2) return
    setIsLoading(true)
    setError(null)
    try {
      const [optRes, cmpRes, efRes] = await Promise.all([
        fetchJSON<{ result: OptimizationResult }>(`/portfolio/optimize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbols,
            model,
            max_weight: maxWeight[0] / 100,
            risk_free_rate: parseFloat(riskFreeRate),
            period,
          }),
        }),
        fetchJSON<CompareData>(`/portfolio/compare`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbols,
            max_weight: maxWeight[0] / 100,
            risk_free_rate: parseFloat(riskFreeRate),
            period,
          }),
        }),
        fetchJSON<FrontierPoint[]>(`/portfolio/efficient-frontier`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbols,
            n_points: 20,
            max_weight: maxWeight[0] / 100,
            risk_free_rate: parseFloat(riskFreeRate),
            period,
          }),
        }),
      ])
      setResult(optRes.result)
      setCompareData(cmpRes)
      setFrontier(efRes)
    } catch (e: any) {
      setError(e.message ?? "优化失败")
    } finally {
      setIsLoading(false)
    }
  }

  // ── 权重饼图 ────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!pieChartRef.current || !result) return
    if (!pieChartInstance.current) {
      pieChartInstance.current = echarts.init(pieChartRef.current)
    }
    const chart = pieChartInstance.current
    const data = Object.entries(result.weights)
      .filter(([, w]) => w > 0.001)
      .map(([name, value]) => ({ name, value: +(value * 100).toFixed(2) }))

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: "{b}: {c}%" },
      series: [{
        type: "pie",
        radius: ["40%", "70%"],
        center: ["50%", "50%"],
        data,
        label: { color: "#94a3b8", fontSize: 10, formatter: "{b}\n{c}%" },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.3)" } },
      }],
    }, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [result])

  // ── 风险贡献柱状图 ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!riskChartRef.current || !result) return
    if (!riskChartInstance.current) {
      riskChartInstance.current = echarts.init(riskChartRef.current)
    }
    const chart = riskChartInstance.current
    const entries = Object.entries(result.risk_contributions)
    const names = entries.map(([n]) => n)
    const values = entries.map(([, v]) => +v.toFixed(2))

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { top: 20, right: 20, bottom: 30, left: 50 },
      xAxis: {
        type: "category",
        data: names,
        axisLabel: { color: "#94a3b8", fontSize: 10 },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      },
      yAxis: {
        type: "value",
        name: "风险贡献 %",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)", type: "dashed" } },
      },
      series: [{
        type: "bar",
        data: values,
        itemStyle: { color: "#a78bfa" },
        barMaxWidth: 32,
      }],
    }, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [result])

  // ── 有效前沿散点图 ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!frontierChartRef.current || !frontier?.length) return
    if (!frontierChartInstance.current) {
      frontierChartInstance.current = echarts.init(frontierChartRef.current)
    }
    const chart = frontierChartInstance.current
    const points = frontier.map((p) => [p.expected_volatility, p.expected_return])

    // 找到最优 Sharpe 点
    let bestIdx = 0
    let bestSharpe = -Infinity
    frontier.forEach((p, i) => {
      if (p.sharpe_ratio > bestSharpe) {
        bestSharpe = p.sharpe_ratio
        bestIdx = i
      }
    })
    const bestPoint = [frontier[bestIdx].expected_volatility, frontier[bestIdx].expected_return]

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: (params: any) => {
          const p = params[0]
          return `波动率: ${p.data[0]}%<br/>收益: ${p.data[1]}%`
        },
      },
      grid: { top: 20, right: 20, bottom: 30, left: 50 },
      xAxis: {
        type: "value",
        name: "波动率 %",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)", type: "dashed" } },
      },
      yAxis: {
        type: "value",
        name: "收益率 %",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)", type: "dashed" } },
      },
      series: [
        {
          type: "line",
          data: points,
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { color: "#34d399", width: 2 },
          itemStyle: { color: "#34d399" },
        },
        {
          type: "scatter",
          data: [bestPoint],
          symbolSize: 14,
          itemStyle: { color: "#fbbf24", borderColor: "#fff", borderWidth: 2 },
          label: { show: true, formatter: "最优", color: "#fbbf24", fontSize: 10, position: "top" },
        },
      ],
    }, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [frontier])

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4 p-4">
      {/* 配置面板 */}
      <div className="glass-card rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="font-semibold text-sm">投资组合优化</h3>
          <Badge variant="outline" className="text-[10px]">TRADE-03</Badge>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">标的列表 (逗号分隔)</label>
            <Input
              value={symbolsInput}
              onChange={(e) => setSymbolsInput(e.target.value)}
              className="font-mono bg-input border-border text-xs"
              placeholder="US.AAPL,US.MSFT,US.NVDA"
            />
          </div>

          <div className="flex items-end gap-4 flex-wrap">
            <div className="w-36">
              <label className="text-xs text-muted-foreground mb-1 block">优化模型</label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger className="bg-input border-border">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODEL_OPTIONS.map((m) => (
                    <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="w-28">
              <label className="text-xs text-muted-foreground mb-1 block">回看周期</label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger className="bg-input border-border">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1y">1 年</SelectItem>
                  <SelectItem value="3y">3 年</SelectItem>
                  <SelectItem value="5y">5 年</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="w-52">
              <label className="text-xs text-muted-foreground mb-1 block">
                单只上限: <span className="font-mono text-foreground">{maxWeight[0]}%</span>
              </label>
              <Slider
                value={maxWeight}
                onValueChange={setMaxWeight}
                min={5}
                max={100}
                step={5}
                className="py-1"
              />
            </div>

            <Button
              onClick={runOptimize}
              disabled={isLoading || symbols.length < 2}
              className="bg-violet-500 hover:bg-violet-600 text-white"
            >
              {isLoading ? "优化中..." : "开始优化"}
            </Button>

            {error && <span className="text-xs text-red-400">{error}</span>}
          </div>
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full glass-card rounded-lg" />
          ))}
        </div>
      )}

      {/* 结果指标 */}
      {result && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <MetricCard label="预期年化收益" value={`${(result.expected_return * 100).toFixed(1)}%`} color="emerald" />
          <MetricCard label="预期年化波动" value={`${(result.expected_volatility * 100).toFixed(1)}%`} color="amber" />
          <MetricCard label="Sharpe 比率" value={result.sharpe_ratio.toFixed(2)} color="blue" />
          <MetricCard label="有效持仓数" value={result.effective_n.toFixed(1)} color="violet" />
        </div>
      )}

      {/* 图表区 */}
      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="glass-card rounded-lg p-4">
            <h4 className="text-xs text-muted-foreground mb-2">权重分布</h4>
            <div ref={pieChartRef} className="w-full h-56" />
          </div>
          <div className="glass-card rounded-lg p-4">
            <h4 className="text-xs text-muted-foreground mb-2">风险贡献</h4>
            <div ref={riskChartRef} className="w-full h-56" />
          </div>
        </div>
      )}

      {/* 有效前沿 */}
      {frontier && (
        <div className="glass-card rounded-lg p-4">
          <h4 className="text-xs text-muted-foreground mb-2">有效前沿</h4>
          <div ref={frontierChartRef} className="w-full h-56" />
        </div>
      )}

      {/* 模型对比表 */}
      {compareData && (
        <div className="glass-card rounded-lg p-4 overflow-x-auto">
          <h4 className="text-xs text-muted-foreground mb-3">模型对比</h4>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-border/50 text-muted-foreground">
                <th className="text-left py-2 px-2">模型</th>
                <th className="text-right py-2 px-2">年化收益</th>
                <th className="text-right py-2 px-2">年化波动</th>
                <th className="text-right py-2 px-2">Sharpe</th>
                <th className="text-right py-2 px-2">有效持仓</th>
                <th className="text-left py-2 px-2">最优权重</th>
              </tr>
            </thead>
            <tbody>
              {compareData.models.map((m) => (
                <tr
                  key={m.name}
                  className={cn(
                    "border-b border-border/20 hover:bg-secondary/40 transition-colors",
                    m.name === compareData.best_model && "bg-emerald-400/5",
                  )}
                >
                  <td className="py-2 px-2">
                    <span className="text-foreground">{MODEL_LABEL[m.name] ?? m.name}</span>
                    {m.name === compareData.best_model && (
                      <Badge variant="outline" className="ml-2 text-[9px] border-emerald-400 text-emerald-400">最优</Badge>
                    )}
                  </td>
                  <td className="text-right py-2 px-2 text-emerald-400">{(m.expected_return * 100).toFixed(1)}%</td>
                  <td className="text-right py-2 px-2 text-amber-400">{(m.expected_volatility * 100).toFixed(1)}%</td>
                  <td className="text-right py-2 px-2 text-blue-400">{m.sharpe_ratio.toFixed(2)}</td>
                  <td className="text-right py-2 px-2 text-foreground">{m.effective_n.toFixed(1)}</td>
                  <td className="py-2 px-2">
                    <div className="flex gap-1 flex-wrap">
                      {Object.entries(m.weights)
                        .filter(([, w]) => w > 0.01)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 3)
                        .map(([sym, w]) => (
                          <span key={sym} className="text-[10px] text-muted-foreground">
                            {sym.split(".").pop()}: {(w * 100).toFixed(0)}%
                          </span>
                        ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!result && !isLoading && (
        <div className="glass-card rounded-lg p-8 text-center text-sm text-muted-foreground">
          输入标的列表并选择优化模型，点击「开始优化」查看组合优化结果
        </div>
      )}
    </div>
  )
}

// ── 辅助组件 ─────────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color: "emerald" | "amber" | "blue" | "violet"
}) {
  const colorMap = {
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    blue: "text-blue-400",
    violet: "text-violet-400",
  }
  return (
    <div className="glass-card rounded-lg p-3 flex flex-col gap-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className={cn("font-mono text-lg font-semibold", colorMap[color])}>{value}</span>
    </div>
  )
}
