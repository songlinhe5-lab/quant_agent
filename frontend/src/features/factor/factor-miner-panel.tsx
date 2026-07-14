'use client'

import React, { useState } from 'react'
import { FlaskConical, Loader2, Sparkles, TrendingUp, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

interface FactorSuggestion {
  name: string
  expression: string
  param_range: Record<string, number[]>
  rationale: string
}

interface FactorSearchResult {
  factor_name: string
  best_params: Record<string, number>
  best_sharpe: number
  best_return: number
  total_combos: number
  top_results: Array<{
    params: Record<string, number>
    sharpe: number
    annualized_return: number
    max_drawdown: number
  }>
}

type Stage = 'idle' | 'suggesting' | 'searching' | 'done' | 'error'

export function FactorMinerPanel() {
  const { toast } = useToast()
  const [symbol, setSymbol] = useState('')
  const [objective, setObjective] = useState('maximize_sharpe')
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState<Stage>('idle')
  const [suggestions, setSuggestions] = useState<FactorSuggestion[]>([])
  const [searchResults, setSearchResults] = useState<FactorSearchResult[]>([])

  const suggestFactors = async () => {
    if (!symbol.trim()) {
      toast({ variant: 'destructive', title: '请输入标的代码' })
      return
    }

    setLoading(true)
    setStage('suggesting')
    setSuggestions([])
    setSearchResults([])

    try {
      const res = await apiClient.post('/factor/suggest', {
        symbol: symbol.trim(),
        objective,
      })

      if (res.data?.factors) {
        setSuggestions(res.data.factors)
        toast({ title: '因子建议已生成', description: `${res.data.factors.length} 个因子候选` })
      }
    } catch (e: unknown) {
      setStage('error')
      const errMsg = e instanceof Error ? e.message : '生成失败'
      toast({ variant: 'destructive', title: '因子建议失败', description: errMsg })
    } finally {
      setLoading(false)
    }
  }

  const searchFactors = async () => {
    if (suggestions.length === 0) return

    setLoading(true)
    setStage('searching')

    try {
      const res = await apiClient.post('/factor/search', {
        symbol: symbol.trim(),
        factors: suggestions.map(s => ({
          name: s.name,
          expression: s.expression,
          param_range: s.param_range,
          rationale: s.rationale,
        })),
      })

      if (res.data?.results) {
        setSearchResults(res.data.results)
        setStage('done')
        toast({ title: '网格搜索完成', description: `已评估 ${res.data.results.length} 个因子` })
      }
    } catch (e: unknown) {
      setStage('error')
      const errMsg = e instanceof Error ? e.message : '搜索失败'
      toast({ variant: 'destructive', title: '网格搜索失败', description: errMsg })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="glass-card rounded-xl border border-border/40 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-border/30 bg-secondary/30 flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">AI 因子挖掘</span>
        <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded font-mono">
          LLM + Grid Search
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* 输入表单 */}
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">标的代码</label>
            <Input
              placeholder="US.AAPL"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="text-sm font-mono"
              disabled={loading}
            />
          </div>
          <div className="w-40">
            <label className="text-xs text-muted-foreground mb-1 block">优化目标</label>
            <select
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
              disabled={loading}
            >
              <option value="maximize_sharpe">最大化 Sharpe</option>
              <option value="minimize_drawdown">最小化回撤</option>
              <option value="maximize_return">最大化收益</option>
            </select>
          </div>
          <Button
            onClick={suggestFactors}
            disabled={loading || !symbol.trim()}
            className="h-9 gap-1.5"
          >
            {loading && stage === 'suggesting' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            AI 建议
          </Button>
        </div>

        {/* 因子建议列表 */}
        {suggestions.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-muted-foreground">因子候选 ({suggestions.length})</h4>
              {stage !== 'searching' && (
                <Button size="sm" variant="outline" onClick={searchFactors} disabled={loading} className="h-7 text-xs gap-1">
                  <TrendingUp className="h-3 w-3" />
                  网格搜索
                </Button>
              )}
            </div>
            <div className="space-y-1.5">
              {suggestions.map((f, i) => (
                <div key={i} className="bg-background/50 rounded-lg px-3 py-2 border border-border/30">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">{f.name}</span>
                    <span className="text-[10px] font-mono text-muted-foreground">{f.expression}</span>
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">{f.rationale}</div>
                  <div className="text-[10px] text-primary/70 font-mono mt-0.5">
                    参数: {Object.entries(f.param_range).map(([k, v]) => `${k}=[${v.join(',')}]`).join(' ')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 搜索结果 */}
        {searchResults.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-muted-foreground">搜索结果</h4>
            <div className="space-y-1.5">
              {searchResults.map((r, i) => (
                <div key={i} className="bg-background/50 rounded-lg px-3 py-2 border border-border/30">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium">{r.factor_name}</span>
                    <div className="flex items-center gap-3 text-[10px] font-mono">
                      <span className="text-green-500">Sharpe: {r.best_sharpe.toFixed(2)}</span>
                      <span className="text-blue-500">Return: {(r.best_return * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    最优参数: {Object.entries(r.best_params).map(([k, v]) => `${k}=${v}`).join(', ')}
                    <span className="ml-2">({r.total_combos} 种组合)</span>
                  </div>
                  {r.top_results?.length > 0 && (
                    <details className="mt-1">
                      <summary className="text-[10px] text-primary cursor-pointer hover:text-primary/80">
                        查看 Top {r.top_results.length} 结果
                      </summary>
                      <div className="mt-1 space-y-0.5">
                        {r.top_results.map((t, j) => (
                          <div key={j} className="flex items-center justify-between text-[10px] font-mono bg-secondary/20 rounded px-2 py-1">
                            <span>{Object.entries(t.params).map(([k, v]) => `${k}=${v}`).join(', ')}</span>
                            <span className="text-green-500">S={t.sharpe.toFixed(2)}</span>
                            <span className="text-blue-500">R={(t.annualized_return * 100).toFixed(1)}%</span>
                            <span className="text-red-500">DD={(t.max_drawdown * 100).toFixed(1)}%</span>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 空状态 */}
        {!loading && suggestions.length === 0 && stage === 'idle' && (
          <div className="text-center py-8 text-muted-foreground">
            <FlaskConical className="h-10 w-10 mx-auto mb-3 opacity-20" />
            <p className="text-xs">输入标的代码，AI 将建议交易因子并进行参数优化</p>
            <p className="text-[10px] mt-1">支持动量/均线/波动率/量价等多种因子类型</p>
          </div>
        )}

        {/* 错误状态 */}
        {stage === 'error' && (
          <div className="flex items-center gap-2 text-red-500 text-xs bg-red-500/5 rounded-lg p-3 border border-red-500/20">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>操作失败，请检查 LLM 服务状态后重试</span>
          </div>
        )}
      </div>
    </div>
  )
}
