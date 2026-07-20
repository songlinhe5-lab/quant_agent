/**
 * 风控进阶面板：板块暴露 / 相关性热力图 / CVaR 分解 / 压力测试
 */

import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { SectorBarChart, CorrelationHeatmap, CVarWaterfallChart } from './risk-charts'
import type { CorrelationData, SectorData, CVarData } from './risk-types'

interface RiskAdvancedPanelProps {
  market: string
  correlation?: CorrelationData
}

export function RiskAdvancedPanel({ market, correlation }: RiskAdvancedPanelProps) {
  const [advancedTab, setAdvancedTab] = useState<'sector' | 'corr' | 'cvar' | 'stress' | null>(null)
  const [sectorData, setSectorData] = useState<SectorData[]>([])
  const [cvarData, setCvarData] = useState<CVarData[]>([])
  const [stressResult, setStressResult] = useState<any>(null)
  const [stressScenario, setStressScenario] = useState('2008_crash')

  useEffect(() => {
    if (advancedTab === 'sector' && sectorData.length === 0) {
      apiClient.get<any>(`/risk/sector-exposure?market=${market}`).then(res => {
        const d = res.data?.data || res.data
        if (d?.sectors) setSectorData(d.sectors)
      }).catch(() => {})
    }
    if (advancedTab === 'cvar' && cvarData.length === 0) {
      apiClient.get<any>(`/risk/cvar?market=${market}`).then(res => {
        const d = res.data?.data || res.data
        if (d?.decompositions) setCvarData(d.decompositions)
      }).catch(() => {})
    }
  }, [advancedTab, market])

  function runStressTest(scenario: string) {
    setStressScenario(scenario)
    apiClient.post<any>(`/risk/stress-test`, { scenario, market }).then(res => {
      const d = res.data?.data || res.data
      setStressResult(d)
    }).catch(() => {})
  }

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-3 py-1 border-b border-border/20 flex items-center gap-1.5">
        {(['sector', 'corr', 'cvar', 'stress'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setAdvancedTab(advancedTab === tab ? null : tab)}
            className={cn(
              'text-[8px] px-1.5 py-0.5 rounded font-semibold transition-colors',
              advancedTab === tab ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {{ sector: '板块', corr: '相关性', cvar: 'CVaR', stress: '压力测试' }[tab]}
          </button>
        ))}
      </div>
      {advancedTab === 'sector' && (
        <div className="p-1.5 h-36">
          {sectorData.length > 0 ? (
            <SectorBarChart data={sectorData} />
          ) : (
            <div className="h-full flex items-center justify-center text-[10px] text-muted-foreground">加载中...</div>
          )}
        </div>
      )}
      {advancedTab === 'corr' && correlation && correlation.labels.length > 1 && (
        <div className="p-1.5 h-44">
          <CorrelationHeatmap labels={correlation.labels} matrix={correlation.matrix} />
          {correlation.warnings.length > 0 && (
            <div className="px-2 py-1 text-[8px] text-amber-500">
              ⚠ 高相关性预警: {correlation.warnings.map(w => `${w.a}↔${w.b}(${w.val.toFixed(2)})`).join(', ')}
            </div>
          )}
        </div>
      )}
      {advancedTab === 'corr' && (!correlation || correlation.labels.length <= 1) && (
        <div className="p-3 text-center text-[9px] text-muted-foreground">持仓不足 2 只，无法计算相关性</div>
      )}
      {advancedTab === 'cvar' && (
        <div className="p-1.5 space-y-1.5">
          {cvarData.length > 0 ? (
            <>
              <div className="h-28"><CVarWaterfallChart data={cvarData} /></div>
              <div className="grid grid-cols-2 gap-1 text-[8px]">
                {cvarData.map(d => (
                  <div key={d.symbol} className="flex justify-between px-1.5 py-0.5 bg-muted/20 rounded">
                    <span className="font-mono font-semibold">{d.symbol}</span>
                    <span className="font-mono tabular-nums text-muted-foreground">{(d.cvar_contrib * 100).toFixed(3)}%</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="py-4 text-center text-[9px] text-muted-foreground">加载中...</div>
          )}
        </div>
      )}
      {advancedTab === 'stress' && (
        <div className="p-2 space-y-1.5">
          <div className="flex flex-wrap gap-1">
            {[
              { id: '2008_crash', label: '🏦 2008 金融危机' },
              { id: '2020_covid', label: '🦠 2020 新冠' },
              { id: '2022_hike', label: '📈 2022 加息' },
              { id: 'vol_double', label: '🌊 波动率翻倍' },
              { id: 'rate_plus_1', label: '💰 利率+1%' },
              { id: 'fx_depreciation', label: '💱 汇率-5%' },
            ].map(s => (
              <button
                key={s.id}
                onClick={() => runStressTest(s.id)}
                className={cn(
                  'text-[8px] px-1.5 py-0.5 rounded border transition-colors',
                  stressScenario === s.id ? 'border-primary text-primary bg-primary/10' : 'border-border/30 text-muted-foreground hover:border-primary/50'
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
          {stressResult ? (
            <div className="grid grid-cols-3 gap-1.5 text-[9px]">
              <div className="bg-muted/20 rounded px-2 py-1">
                <p className="text-muted-foreground text-[8px]">冲击前 NAV</p>
                <p className="font-mono font-bold tabular-nums">${(stressResult.nav_before / 1000).toFixed(1)}K</p>
              </div>
              <div className="bg-muted/20 rounded px-2 py-1">
                <p className="text-muted-foreground text-[8px]">冲击后 NAV</p>
                <p className={cn('font-mono font-bold tabular-nums', stressResult.change_pct < 0 ? 'text-red-500' : 'text-emerald-500')}>
                  ${(stressResult.nav_after / 1000).toFixed(1)}K
                </p>
              </div>
              <div className="bg-muted/20 rounded px-2 py-1">
                <p className="text-muted-foreground text-[8px]">变化</p>
                <p className={cn('font-mono font-bold tabular-nums', stressResult.change_pct < 0 ? 'text-red-500' : 'text-emerald-500')}>
                  {stressResult.change_pct > 0 ? '+' : ''}{stressResult.change_pct}%
                </p>
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-[9px] text-muted-foreground">选择情景执行压力测试</div>
          )}
        </div>
      )}
    </div>
  )
}
