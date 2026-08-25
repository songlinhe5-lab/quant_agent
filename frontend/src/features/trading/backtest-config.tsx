/**
 * 回测配置面板：参数输入 + 进度条 + 动态策略表单
 */

import { useState } from 'react'
import { FlaskConical, Play, CheckCircle, Square, ChevronDown } from 'lucide-react'
import { validate } from '../quotes/custom-indicator/engine'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DynamicStrategyForm } from '@/features/strategy/dynamic-strategy-form'
import { SnapshotPicker } from '@/features/backtest/snapshot-picker'

interface BacktestConfigProps {
  running: boolean
  done: boolean
  progress: number
  progressStage: string
  ticker: string; setTicker: (v: string) => void
  period: string; setPeriod: (v: string) => void
  interval: string; setIntervalVal: (v: string) => void
  initialCapital: number; setInitialCapital: (v: number) => void
  dataSource: string; setDataSource: (v: string) => void
  isDebugMode: boolean; setIsDebugMode: (v: boolean) => void
  dataSnapshotId: string; setDataSnapshotId: (v: string) => void
  strategies: any[]
  selectedStrategy: string
  formSchema: any[]
  strategyParams: Record<string, any>
  handleRun: (params?: Record<string, any>, isSilent?: boolean) => void
  handleCancel: () => void
  handleStrategyChange: (name: string) => void
  setDone: (v: boolean) => void
  setProgress: (v: number) => void
  setStrategyParams: (v: Record<string, any>) => void
  customExpr: string
  setCustomExpr: (v: string) => void
  /** UIRF-05: 回测成本/复现参数显性化 */
  reproParams: { atr_multiplier: number; commission_pct: number; slippage_pct: number; random_seed: number }
  setReproParams: (v: { atr_multiplier: number; commission_pct: number; slippage_pct: number; random_seed: number }) => void
}

export function BacktestConfig(props: BacktestConfigProps) {
  const {
    running, done, progress, progressStage, ticker, setTicker, period, setPeriod,
    interval, setIntervalVal, initialCapital, setInitialCapital,
    dataSource, setDataSource, isDebugMode, setIsDebugMode,
    dataSnapshotId, setDataSnapshotId, strategies, selectedStrategy,
    formSchema, handleRun, handleCancel, handleStrategyChange,
    setDone, setProgress, setStrategyParams,
    customExpr, setCustomExpr, reproParams, setReproParams,
  } = props

  // 高级与复现区折叠态 (shadcn Collapsible 受控)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  return (
    <div className="glass-card rounded-lg overflow-hidden transition-colors duration-300">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">回测配置</span>
      </div>
      <div className="p-4">
        <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 mb-4">
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">执行策略</p>
            {/* 保留原生 select：shadcn Select 不支持 optgroup 三分组（内置引擎/我的草稿/自定义），
                样式对齐 Input 控件视觉（同尺寸/圆角/焦点环） */}
            <select value={selectedStrategy} onChange={e => handleStrategyChange(e.target.value)} disabled={running || done} className="bg-background border-input dark:bg-input/30 rounded-md border px-2 py-1.5 text-xs shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 w-full cursor-pointer">
              {/* 内置引擎（前端常量集, 非用户草稿） */}
              <optgroup label="内置引擎">
                <option value="">内置底背离共振 (默认)</option>
              </optgroup>
              {/* 我的草稿（真实状态来自后端 status 字段） */}
              <optgroup label="我的草稿">
                {strategies.map((s, i) => (
                  <option key={i} value={s.name}>
                    {s.name}（{s.status === 'deployed' ? '已部署' : s.status === 'backtested' ? '已回测' : '草稿'}）
                  </option>
                ))}
              </optgroup>
              {/* 自定义指标脚本 (Pine) */}
              <optgroup label="自定义">
                <option value="__custom_expr__">自定义指标脚本 (Pine)</option>
              </optgroup>
            </select>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">测试标的</p>
            <Input type="text" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} className="h-8 text-xs font-mono uppercase" disabled={running || done} />
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">回测区间</p>
            <Select value={period} onValueChange={setPeriod} disabled={running || done}>
              <SelectTrigger className="h-8 w-full text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="1mo">1 个月</SelectItem>
                  <SelectItem value="3mo">3 个月</SelectItem>
                  <SelectItem value="6mo">6 个月</SelectItem>
                  <SelectItem value="1y">1 年</SelectItem>
                  <SelectItem value="2y">2 年</SelectItem>
                  <SelectItem value="5y">5 年</SelectItem>
                  <SelectItem value="max">全部历史</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">数据粒度</p>
            <Select value={interval} onValueChange={setIntervalVal} disabled={running || done}>
              <SelectTrigger className="h-8 w-full text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="1d">1 日 (1d)</SelectItem>
                  <SelectItem value="1h">1 小时 (1h)</SelectItem>
                  <SelectItem value="15m">15 分钟 (15m)</SelectItem>
                  <SelectItem value="5m">5 分钟 (5m)</SelectItem>
                  <SelectItem value="1m">1 分钟 (1m)</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">初始资金</p>
            <Input type="number" value={initialCapital} onChange={e => setInitialCapital(Number(e.target.value))} disabled={running || done} className="h-8 text-xs font-mono tabular-nums" />
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">数据源</p>
            <Select value={dataSource} onValueChange={setDataSource} disabled={running || done}>
              <SelectTrigger className="h-8 w-full text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="auto">智能路由 (Auto)</SelectItem>
                  <SelectItem value="futu">富途 OpenD (Futu)</SelectItem>
                  <SelectItem value="yfinance">雅虎财经 (YFinance)</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">调试模式</p>
            <div className="flex items-center gap-2 h-[26px]">
              <Switch id="debugModeBT" checked={isDebugMode} onCheckedChange={setIsDebugMode} disabled={running || done} />
              <label htmlFor="debugModeBT" className="text-xs text-muted-foreground cursor-pointer select-none">记录逐K线日志</label>
            </div>
          </div>
        </div>

        {selectedStrategy === '__custom_expr__' && (
          <div className="mb-4 p-3 rounded-lg border border-primary/30 bg-primary/5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-foreground">自定义指标脚本 (Pine 风格)</span>
              <span className="text-[9px] text-muted-foreground">作为条件触发信号源</span>
            </div>
            <Textarea
              value={customExpr}
              onChange={(e) => setCustomExpr(e.target.value)}
              disabled={running || done}
              placeholder="例：CROSS(MA(CLOSE,5), MA(CLOSE,20))  或  RSI(14) > 70"
              rows={2}
              className="min-h-0 text-xs font-mono resize-none"
            />
            {customExpr.trim() && !validate(customExpr).ok && (
              <div className="text-[10px] text-red-400">语法错误：{validate(customExpr).error}</div>
            )}
            {customExpr.trim() && validate(customExpr).ok && (
              <div className="text-[10px] text-emerald-400">✓ 表达式有效，点击「启动回测」用真实历史 K 线运行</div>
            )}
          </div>
        )}

        <div className="mb-4 max-w-md">
          <SnapshotPicker value={dataSnapshotId} onChange={setDataSnapshotId} disabled={running || done} />
        </div>

        {running && (
          <div className="mb-4 p-3 rounded-lg bg-secondary/40 border border-border/30">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold font-mono flex items-center gap-1.5">
                回测进行中…
                <button onClick={handleCancel} className="p-0.5 rounded bg-red-500/10 hover:bg-red-500/20 text-red-500 transition-colors" title="中止回测"><Square className="h-3 w-3 fill-current" /></button>
              </span>
              <span className="text-xs font-mono tabular-nums text-primary">{Math.round(progress)}%</span>
            </div>
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
            {/* UIRF-04: 只渲染后端 NDJSON 真实 stage/detail 事件，删除写死的假装饰日志 */}
            <div className="mt-2 bg-slate-50 dark:bg-[oklch(0.09_0.005_270)] rounded p-2 font-mono text-[10px] text-muted-foreground max-h-20 overflow-y-auto transition-colors duration-300">
              {progressStage ? (
                <div><span className="text-sky-600 dark:text-sky-400 transition-colors duration-300">[STAGE]</span> {progressStage}</div>
              ) : (
                <div><span className="text-sky-600 dark:text-sky-400 transition-colors duration-300">[STAGE]</span> 等待后端事件…</div>
              )}
            </div>
          </div>
        )}

        {formSchema.length > 0 && (
          <div className="mb-4 pt-4 border-t border-border/30 animate-in fade-in slide-in-from-top-2">
            <DynamicStrategyForm
              schema={formSchema}
              onSubmit={(className, data, isSilent) => { setStrategyParams(data); handleRun(data, isSilent); }}
            />
          </div>
        )}

        {/* UIRF-05: 高级与复现 —— 成本/复现参数显性化，ReproducibilityBadge 与实际 payload 一致 */}
        <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen} className="mb-4 border border-border/30 rounded-lg">
          <CollapsibleTrigger className="flex items-center gap-1 cursor-pointer select-none px-3 py-2 text-[11px] font-semibold text-muted-foreground hover:text-foreground w-full">
            ⚙️ 高级与复现（ATR/成本/滑点/随机种子）
            <ChevronDown className={`h-3 w-3 ml-auto transition-transform ${advancedOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
          </CollapsibleTrigger>
          <CollapsibleContent>
          <div className="grid grid-cols-2 gap-2 px-3 pb-3">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">ATR 倍数</span>
              <Input type="number" step="0.5" value={reproParams.atr_multiplier} onChange={(e) => setReproParams({ ...reproParams, atr_multiplier: parseFloat(e.target.value) || 2.0 })} className="h-7 text-[11px]" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">手续费率</span>
              <Input type="number" step="0.0001" value={reproParams.commission_pct} onChange={(e) => setReproParams({ ...reproParams, commission_pct: parseFloat(e.target.value) || 0.0005 })} className="h-7 text-[11px]" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">滑点率</span>
              <Input type="number" step="0.0001" value={reproParams.slippage_pct} onChange={(e) => setReproParams({ ...reproParams, slippage_pct: parseFloat(e.target.value) || 0.001 })} className="h-7 text-[11px]" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">随机种子</span>
              <Input type="number" step="1" value={reproParams.random_seed} onChange={(e) => setReproParams({ ...reproParams, random_seed: parseInt(e.target.value) || 42 })} className="h-7 text-[11px]" />
            </label>
          </div>
          </CollapsibleContent>
        </Collapsible>

        <div className="flex gap-2 flex-wrap">
          {formSchema.length === 0 && (
            <>
              <Button className="gap-2 text-sm" onClick={() => handleRun()} disabled={running || done}>
                {done
                  ? <><CheckCircle className="h-4 w-4" aria-hidden="true" />回测完成</>
                  : running
                    ? <><FlaskConical className="h-4 w-4 animate-spin" aria-hidden="true" />运行中…</>
                    : <><Play className="h-4 w-4" aria-hidden="true" />启动回测 · 单次沙箱推演</>
                }
              </Button>
              {running && (
                <Button variant="destructive" className="gap-2 text-sm h-9" onClick={handleCancel}>
                  <Square className="h-4 w-4 fill-current" /> 中止
                </Button>
              )}
            </>
          )}
          {done && (
            <Button variant="outline" size="sm" className="text-xs h-9" onClick={() => { setDone(false); setProgress(0) }}>
              重新回测
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
