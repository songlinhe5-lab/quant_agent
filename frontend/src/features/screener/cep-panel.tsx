'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Radio, Plus, Trash2, Loader2, AlertTriangle, Activity, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { apiClient } from '@/lib/api-client'
import { useToast } from '@/hooks/use-toast'

interface CEPRule {
  id: string
  name: string
  expression: string
  watchlist: string[]
  enabled: boolean
  created_at: number
}

interface CEPMatch {
  rule_id: string
  rule_name: string
  symbol: string
  expression: string
  indicators: Record<string, number>
  matched_at: number
}

export function CEPPanel() {
  const { toast } = useToast()
  const [rules, setRules] = useState<CEPRule[]>([])
  const [matches, setMatches] = useState<CEPMatch[]>([])
  const [loading, setLoading] = useState(false)
  const [newName, setNewName] = useState('')
  const [newExpr, setNewExpr] = useState('')
  const [newWatchlist, setNewWatchlist] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 加载规则列表
  const fetchRules = useCallback(async () => {
    try {
      const res = await apiClient.get('/screener/cep/rules')
      if (res.data?.status === 'success') setRules(res.data.data)
    } catch { /* ignore */ }
  }, [])

  // 加载匹配事件
  const fetchMatches = useCallback(async () => {
    try {
      const res = await apiClient.get('/screener/cep/matches')
      if (res.data?.status === 'success') setMatches(res.data.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchRules()
    fetchMatches()
    // 轮询匹配事件 (每 3 秒)
    pollRef.current = setInterval(fetchMatches, 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchRules, fetchMatches])

  const addRule = async () => {
    if (!newName.trim() || !newExpr.trim()) {
      toast({ variant: 'destructive', title: '请填写规则名称和表达式' })
      return
    }
    setLoading(true)
    try {
      const watchlist = newWatchlist.split(',').map(s => s.trim()).filter(Boolean)
      const res = await apiClient.post('/screener/cep/rules', {
        name: newName,
        expression: newExpr,
        watchlist,
      })
      if (res.data?.status === 'success') {
        toast({ title: '规则创建成功', description: `"${newName}" 已开始监控` })
        setNewName('')
        setNewExpr('')
        setNewWatchlist('')
        fetchRules()
      }
    } catch (e: any) {
      toast({ variant: 'destructive', title: '创建失败', description: e.response?.data?.detail || e.message })
    } finally {
      setLoading(false)
    }
  }

  const deleteRule = async (id: string) => {
    try {
      await apiClient.delete(`/screener/cep/rules/${id}`)
      setRules(prev => prev.filter(r => r.id !== id))
      toast({ title: '规则已删除' })
    } catch {
      toast({ variant: 'destructive', title: '删除失败' })
    }
  }

  return (
    <div className="glass-card rounded-xl border border-border/40 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-border/30 bg-secondary/30 flex items-center gap-2">
        <Radio className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">CEP 实时异动监控</span>
        <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded font-mono">
          {rules.length} 条规则 · {matches.length} 个匹配
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* 新建规则表单 */}
        <div className="bg-secondary/20 rounded-lg p-3 border border-border/40 space-y-2">
          <div className="flex items-center gap-2">
            <Input
              placeholder="规则名称 (如: RSI 超卖反弹)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="h-8 text-xs"
            />
            <Button size="sm" onClick={addRule} disabled={loading} className="h-8 px-3 gap-1">
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
              添加
            </Button>
          </div>
          <Input
            placeholder="表达式: RSI(14) < 30 AND MACD.histogram > 0"
            value={newExpr}
            onChange={(e) => setNewExpr(e.target.value)}
            className="h-8 text-xs font-mono"
          />
          <Input
            placeholder="监控标的 (逗号分隔): US.AAPL, HK.0700, US.NVDA"
            value={newWatchlist}
            onChange={(e) => setNewWatchlist(e.target.value)}
            className="h-8 text-xs font-mono"
          />
        </div>

        {/* 规则列表 */}
        {rules.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold text-muted-foreground">活跃规则</h4>
            {rules.map(rule => (
              <div key={rule.id} className="flex items-center justify-between bg-background/50 rounded-lg px-3 py-2 border border-border/30">
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate">{rule.name}</div>
                  <div className="text-[10px] text-muted-foreground font-mono truncate">{rule.expression}</div>
                  <div className="text-[10px] text-muted-foreground">{rule.watchlist.length} 只标的</div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => deleteRule(rule.id)} className="h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-red-500/10">
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* 匹配事件流 */}
        {matches.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-green-500" /> 实时匹配
            </h4>
            <div className="space-y-1 max-h-64 overflow-y-auto custom-scrollbar">
              {matches.slice().reverse().map((m, i) => (
                <div key={`${m.rule_id}-${m.symbol}-${m.matched_at}`} className={`flex items-center gap-3 rounded-lg px-3 py-2 border text-xs ${i === 0 ? 'bg-green-500/5 border-green-500/20 animate-pulse' : 'bg-background/30 border-border/20'}`}>
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium">{m.symbol}</span>
                    <span className="text-muted-foreground ml-2">触发: {m.rule_name}</span>
                  </div>
                  <div className="text-[10px] text-muted-foreground font-mono shrink-0">
                    {new Date(m.matched_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {rules.length === 0 && matches.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            <Radio className="h-10 w-10 mx-auto mb-3 opacity-20" />
            <p className="text-xs">暂无监控规则，请在上方创建 CEP 规则</p>
            <p className="text-[10px] mt-1">支持表达式: RSI(14) &lt; 30, MACD.histogram &gt; 0, RSI &gt; KDJ.K 等</p>
          </div>
        )}
      </div>
    </div>
  )
}
