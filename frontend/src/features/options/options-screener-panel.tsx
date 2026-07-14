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

interface OptionGreeks {
  delta: number
  gamma: number
  vega: number
  theta: number
  rho: number
}

interface OptionRow {
  symbol: string
  strike: number
  expiry: string
  option_type: "CALL" | "PUT"
  iv: number
  iv_rank: number
  iv_percentile: number
  greeks: OptionGreeks
  bid: number
  ask: number
  volume: number
  open_interest: number
  signal?: string
}

interface VolSmilePoint {
  strike: number
  call_iv: number
  put_iv: number
  avg_iv: number
}

interface VolSmileData {
  expiry: string
  points: VolSmilePoint[]
  skew_25d: number
  smile_width: number
}

interface IvRankData {
  current_iv: number
  iv_rank: number
  iv_percentile: number
  iv_52w_high: number
  iv_52w_low: number
  signal: string
}

interface OptionsScreenerPanelProps {
  ticker?: string
}

// ── API 请求封装 ─────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, options)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.data ?? json
}

// ── 组件 ─────────────────────────────────────────────────────────────────────

export function OptionsScreenerPanel({ ticker: initialTicker }: OptionsScreenerPanelProps) {
  const [ticker, setTicker] = useState(initialTicker ?? "US.AAPL")
  const [expiry, setExpiry] = useState("")
  const [greeksRows, setGreeksRows] = useState<OptionRow[]>([])
  const [volSmile, setVolSmile] = useState<VolSmileData | null>(null)
  const [ivRank, setIvRank] = useState<IvRankData | null>(null)
  const [ivRankMin, setIvRankMin] = useState(0)
  const [ivRankMax, setIvRankMax] = useState(100)
  const [minVolume, setMinVolume] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const smileChartRef = useRef<HTMLDivElement>(null)
  const ivGaugeRef = useRef<HTMLDivElement>(null)
  const smileChartInstance = useRef<echarts.ECharts | null>(null)
  const gaugeChartInstance = useRef<echarts.ECharts | null>(null)

  // ── 加载数据 ────────────────────────────────────────────────────────────────

  async function loadData() {
    if (!ticker.trim()) return
    setIsLoading(true)
    setError(null)
    try {
      const [g, vs, iv] = await Promise.all([
        fetchJSON<OptionRow[]>(`/options/greeks/${encodeURIComponent(ticker)}`),
        fetchJSON<VolSmileData>(`/options/vol-smile/${encodeURIComponent(ticker)}`),
        fetchJSON<IvRankData>(`/options/iv-rank/${encodeURIComponent(ticker)}`),
      ])
      setGreeksRows(g)
      setVolSmile(vs)
      setIvRank(iv)
    } catch (e: any) {
      setError(e.message ?? "加载失败")
    } finally {
      setIsLoading(false)
    }
  }

  // ── 筛选逻辑 ────────────────────────────────────────────────────────────────

  const filteredRows = greeksRows.filter((r) => {
    if (r.iv_rank < ivRankMin || r.iv_rank > ivRankMax) return false
    if (r.volume < minVolume) return false
    if (expiry && r.expiry !== expiry) return false
    return true
  })

  // ── 波动率微笑 ECharts ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!smileChartRef.current || !volSmile?.points?.length) return
    if (!smileChartInstance.current) {
      smileChartInstance.current = echarts.init(smileChartRef.current)
    }
    const chart = smileChartInstance.current
    const strikes = volSmile.points.map((p) => p.strike)
    const callIv = volSmile.points.map((p) => p.call_iv)
    const putIv = volSmile.points.map((p) => p.put_iv)

    const option = {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["Call IV", "Put IV"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { top: 30, right: 20, bottom: 30, left: 50 },
      xAxis: {
        type: "category",
        data: strikes.map(String),
        name: "行权价",
        axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      },
      yAxis: {
        type: "value",
        name: "IV %",
        axisLabel: { color: "#94a3b8", fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)", type: "dashed" } },
      },
      series: [
        {
          name: "Call IV",
          type: "scatter",
          data: callIv.map((v) => +(v * 100).toFixed(2)),
          itemStyle: { color: "#34d399" },
          symbolSize: 8,
        },
        {
          name: "Put IV",
          type: "scatter",
          data: putIv.map((v) => +(v * 100).toFixed(2)),
          itemStyle: { color: "#f87171" },
          symbolSize: 8,
        },
      ],
    }
    chart.setOption(option, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => {
      window.removeEventListener("resize", onResize)
    }
  }, [volSmile])

  // ── IV Rank 仪表盘 ECharts ──────────────────────────────────────────────────

  useEffect(() => {
    if (!ivGaugeRef.current || !ivRank) return
    if (!gaugeChartInstance.current) {
      gaugeChartInstance.current = echarts.init(ivGaugeRef.current)
    }
    const chart = gaugeChartInstance.current
    const rank = ivRank.iv_rank
    const gaugeColor = rank < 30 ? "#34d399" : rank < 70 ? "#fbbf24" : "#f87171"

    const option = {
      backgroundColor: "transparent",
      series: [
        {
          type: "gauge",
          min: 0,
          max: 100,
          progress: { show: true, width: 14, itemStyle: { color: gaugeColor } },
          axisLine: { lineStyle: { width: 14, color: [[1, "rgba(255,255,255,0.08)"]] } },
          axisTick: { show: false },
          splitLine: { length: 8, lineStyle: { width: 2, color: "rgba(255,255,255,0.15)" } },
          axisLabel: { distance: 14, color: "#94a3b8", fontSize: 10 },
          detail: {
            valueAnimation: true,
            formatter: "{value}",
            color: gaugeColor,
            fontSize: 22,
            fontWeight: "bold",
            offsetCenter: [0, "65%"],
          },
          data: [{ value: +rank.toFixed(1), name: "IV Rank" }],
          title: { offsetCenter: [0, "90%"], fontSize: 11, color: "#94a3b8" },
        },
      ],
    }
    chart.setOption(option, true)
    const onResize = () => chart.resize()
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [ivRank])

  // ── 到期日选项 ─────────────────────────────────────────────────────────────

  const expiryOptions = Array.from(new Set(greeksRows.map((r) => r.expiry))).sort()

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4 p-4">
      {/* 顶部：标的输入 + 到期日 + 加载 */}
      <div className="glass-card rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="font-semibold text-sm">高级期权筛选器</h3>
          <Badge variant="outline" className="text-[10px]">TRADE-01</Badge>
        </div>

        <div className="flex items-end gap-3 flex-wrap">
          <div className="w-40">
            <label className="text-xs text-muted-foreground mb-1 block">标的代码</label>
            <Input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="US.AAPL"
              className="font-mono bg-input border-border"
              onKeyDown={(e) => e.key === "Enter" && loadData()}
            />
          </div>

          <div className="w-36">
            <label className="text-xs text-muted-foreground mb-1 block">到期日</label>
            <Select value={expiry} onValueChange={setExpiry}>
              <SelectTrigger className="bg-input border-border">
                <SelectValue placeholder="全部" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部到期日</SelectItem>
                {expiryOptions.map((e) => (
                  <SelectItem key={e} value={e}>{e}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button onClick={loadData} disabled={isLoading || !ticker.trim()} className="bg-violet-500 hover:bg-violet-600 text-white">
            {isLoading ? "加载中..." : "分析"}
          </Button>

          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
      </div>

      {/* IV Rank 仪表盘 + 统计 */}
      {ivRank && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="glass-card rounded-lg p-4 flex flex-col items-center">
            <h4 className="text-xs text-muted-foreground mb-2 self-start">IV Rank 仪表盘</h4>
            <div ref={ivGaugeRef} className="w-full h-40" />
            <div className="grid grid-cols-3 gap-2 text-xs w-full mt-2">
              <div className="text-center">
                <div className="text-muted-foreground">当前 IV</div>
                <div className="font-mono font-medium text-foreground">{(ivRank.current_iv * 100).toFixed(1)}%</div>
              </div>
              <div className="text-center">
                <div className="text-muted-foreground">52周低</div>
                <div className="font-mono text-emerald-400">{(ivRank.iv_52w_low * 100).toFixed(1)}%</div>
              </div>
              <div className="text-center">
                <div className="text-muted-foreground">52周高</div>
                <div className="font-mono text-red-400">{(ivRank.iv_52w_high * 100).toFixed(1)}%</div>
              </div>
            </div>
            <Badge
              variant="outline"
              className={cn(
                "mt-2 text-[10px]",
                ivRank.signal === "HIGH_IV_SELL" && "border-red-400 text-red-400",
                ivRank.signal === "LOW_IV_BUY" && "border-emerald-400 text-emerald-400",
                ivRank.signal === "MODERATE_HIGH" && "border-amber-400 text-amber-400",
                ivRank.signal === "MODERATE_LOW" && "border-blue-400 text-blue-400",
              )}
            >
              {ivRank.signal === "HIGH_IV_SELL" && "高 IV · 卖方信号"}
              {ivRank.signal === "LOW_IV_BUY" && "低 IV · 买方信号"}
              {ivRank.signal === "MODERATE_HIGH" && "中高 IV"}
              {ivRank.signal === "MODERATE_LOW" && "中低 IV"}
              {!["HIGH_IV_SELL", "LOW_IV_BUY", "MODERATE_HIGH", "MODERATE_LOW"].includes(ivRank.signal) && ivRank.signal}
            </Badge>
          </div>

          {/* 波动率微笑曲线 */}
          <div className="glass-card rounded-lg p-4 lg:col-span-2">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs text-muted-foreground">波动率微笑曲线</h4>
              {volSmile && (
                <div className="flex gap-3 text-xs">
                  <span className="text-muted-foreground">
                    Skew 25D: <span className="font-mono text-foreground">{volSmile.skew_25d?.toFixed(3) ?? "—"}</span>
                  </span>
                  <span className="text-muted-foreground">
                    Smile Width: <span className="font-mono text-foreground">{volSmile.smile_width?.toFixed(3) ?? "—"}</span>
                  </span>
                </div>
              )}
            </div>
            <div ref={smileChartRef} className="w-full h-44" />
          </div>
        </div>
      )}

      {/* 筛选条件 */}
      <div className="glass-card rounded-lg p-4">
        <h4 className="text-xs text-muted-foreground mb-3">筛选条件</h4>
        <div className="flex items-end gap-6 flex-wrap">
          <div className="w-52">
            <label className="text-xs text-muted-foreground mb-1 block">
              IV Rank 范围: <span className="font-mono text-foreground">{ivRankMin}–{ivRankMax}</span>
            </label>
            <Slider
              value={[ivRankMin, ivRankMax]}
              onValueChange={([lo, hi]) => { setIvRankMin(lo); setIvRankMax(hi) }}
              min={0}
              max={100}
              step={1}
              className="py-1"
            />
          </div>
          <div className="w-32">
            <label className="text-xs text-muted-foreground mb-1 block">最小成交量</label>
            <Input
              type="number"
              value={minVolume}
              onChange={(e) => setMinVolume(Number(e.target.value))}
              className="font-mono bg-input border-border"
              min={0}
            />
          </div>
          <span className="text-xs text-muted-foreground">
            匹配: <span className="font-mono text-foreground">{filteredRows.length}</span> 条
          </span>
        </div>
      </div>

      {/* Greeks 结果表格 */}
      <div className="glass-card rounded-lg p-4 overflow-x-auto">
        <h4 className="text-xs text-muted-foreground mb-3">
          Greeks 分析结果
          <span className="ml-2 font-mono text-foreground">{filteredRows.length} 条</span>
        </h4>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : filteredRows.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            {greeksRows.length === 0 ? '请输入标的代码并点击「分析」' : '当前筛选条件无匹配结果'}
          </div>
        ) : (
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-border/50 text-muted-foreground">
                <th className="text-left py-2 px-2">行权价</th>
                <th className="text-left py-2 px-1">类型</th>
                <th className="text-right py-2 px-1">IV</th>
                <th className="text-right py-2 px-1">IV Rank</th>
                <th className="text-right py-2 px-1">Delta</th>
                <th className="text-right py-2 px-1">Gamma</th>
                <th className="text-right py-2 px-1">Vega</th>
                <th className="text-right py-2 px-1">Theta</th>
                <th className="text-right py-2 px-1">Rho</th>
                <th className="text-right py-2 px-1">Bid</th>
                <th className="text-right py-2 px-1">Ask</th>
                <th className="text-right py-2 px-1">成交量</th>
                <th className="text-right py-2 px-1">OI</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.slice(0, 100).map((row, i) => (
                <tr
                  key={`${row.strike}-${row.option_type}-${i}`}
                  className="border-b border-border/20 hover:bg-secondary/40 transition-colors"
                >
                  <td className="py-1.5 px-2 text-foreground">{row.strike}</td>
                  <td className={cn("py-1.5 px-1", row.option_type === "CALL" ? "text-emerald-400" : "text-red-400")}>
                    {row.option_type === "CALL" ? "C" : "P"}
                  </td>
                  <td className="text-right py-1.5 px-1 text-foreground">{(row.iv * 100).toFixed(1)}%</td>
                  <td className={cn(
                    "text-right py-1.5 px-1",
                    row.iv_rank < 30 ? "text-emerald-400" : row.iv_rank < 70 ? "text-amber-400" : "text-red-400"
                  )}>
                    {row.iv_rank.toFixed(0)}
                  </td>
                  <td className="text-right py-1.5 px-1 text-blue-300">{row.greeks.delta.toFixed(3)}</td>
                  <td className="text-right py-1.5 px-1 text-violet-300">{row.greeks.gamma.toFixed(4)}</td>
                  <td className="text-right py-1.5 px-1 text-cyan-300">{row.greeks.vega.toFixed(3)}</td>
                  <td className="text-right py-1.5 px-1 text-amber-300">{row.greeks.theta.toFixed(3)}</td>
                  <td className="text-right py-1.5 px-1 text-pink-300">{row.greeks.rho.toFixed(3)}</td>
                  <td className="text-right py-1.5 px-1 text-muted-foreground">{row.bid.toFixed(2)}</td>
                  <td className="text-right py-1.5 px-1 text-muted-foreground">{row.ask.toFixed(2)}</td>
                  <td className="text-right py-1.5 px-1 text-foreground">{row.volume.toLocaleString()}</td>
                  <td className="text-right py-1.5 px-1 text-muted-foreground">{row.open_interest.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
