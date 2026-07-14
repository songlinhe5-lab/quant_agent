import React from 'react'
import { Settings2 } from 'lucide-react'
import { useStrategyStore } from '../stores'
import { SnapshotPicker } from '@/features/backtest/snapshot-picker'

export function SandboxEnvForm() {
  const store = useStrategyStore()

  return (
    <div className="flex flex-col gap-3 p-3 bg-secondary/20 border border-border/30 rounded-xl animate-in fade-in">
      <div className="flex items-center gap-2 mb-1">
        <Settings2 className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground tracking-wide uppercase">沙箱环境配置</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] text-muted-foreground font-mono">测试标的</span>
          <input
            type="text"
            value={store.testTicker}
            onChange={(e) => store.setTestTicker(e.target.value.toUpperCase())}
            className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary uppercase transition-all"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] text-muted-foreground font-mono">初始资金</span>
          <input
            type="number"
            value={store.initialCapital}
            onChange={(e) => store.setInitialCapital(e.target.value)}
            className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary transition-all"
            step="10000"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] text-muted-foreground font-mono">回测时长</span>
          <select
            value={store.backtestPeriod}
            onChange={(e) => store.setBacktestPeriod(e.target.value)}
            className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary cursor-pointer transition-all"
          >
            <option value="1mo">1 个月</option>
            <option value="3mo">3 个月</option>
            <option value="6mo">6 个月</option>
            <option value="1y">1 年</option>
            <option value="2y">2 年</option>
            <option value="5y">5 年</option>
            <option value="max">全部历史</option>
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] text-muted-foreground font-mono">数据源</span>
          <select
            value={store.dataSource}
            onChange={(e) => store.setDataSource(e.target.value)}
            className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-primary cursor-pointer transition-all"
          >
            <option value="auto">智能路由</option>
            <option value="futu">富途 OpenD</option>
            <option value="yfinance">Yahoo</option>
          </select>
        </div>
      </div>

      <SnapshotPicker value={store.dataSnapshotId} onChange={store.setDataSnapshotId} />

      <div className="flex items-center gap-1.5 pt-1 border-t border-border/30">
        <input
          type="checkbox"
          id="debugMode"
          checked={store.isDebugMode}
          onChange={(e) => store.setIsDebugMode(e.target.checked)}
          className="rounded-sm border-border accent-primary focus:ring-primary/30 w-3 h-3 cursor-pointer"
        />
        <label htmlFor="debugMode" className="text-[10px] text-muted-foreground font-mono cursor-pointer select-none">
          记录内部调试日志
        </label>
      </div>
    </div>
  )
}
