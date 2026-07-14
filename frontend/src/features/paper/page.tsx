/**
 * PT-02b: 纸面组合列表页
 */
'use client'

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, TrendingUp, TrendingDown, Pause, Play, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { CreatePortfolioDialog } from './create-portfolio-dialog'

interface PortfolioSummary {
  id: string
  name: string
  strategy_name: string
  market: string
  status: string
  initial_capital: number
  created_at: string
}

const STATUS_META: Record<string, { label: string; class: string }> = {
  running: { label: '运行中', class: 'text-green-500' },
  paused: { label: '已暂停', class: 'text-yellow-500' },
  closed: { label: '已关闭', class: 'text-red-500' },
}

const REFRESH_INTERVAL = 30000

export function PaperListPage() {
  const navigate = useNavigate()
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  const fetchPortfolios = useCallback(async () => {
    try {
      const res = await apiClient.get<any>('/paper/portfolios')
      setPortfolios(res.data?.data || [])
    } catch {
      /* toast handled by apiClient */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPortfolios()
    const timer = setInterval(fetchPortfolios, REFRESH_INTERVAL)
    return () => clearInterval(timer)
  }, [fetchPortfolios])

  const handleAction = async (pid: string, action: 'pause' | 'resume' | 'close') => {
    try {
      await apiClient.post(`/paper/portfolios/${pid}/${action}`)
      fetchPortfolios()
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">纸面组合</h1>
          <p className="text-sm text-muted-foreground">SimBroker 虚拟账本 · 绩效追踪</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchPortfolios}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            创建组合
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : portfolios.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
          <p className="text-sm">暂无纸面组合</p>
          <button
            onClick={() => setShowCreate(true)}
            className="mt-2 text-sm text-primary hover:underline"
          >
            创建第一个组合
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">名称</th>
                <th className="text-left px-4 py-2.5 font-medium">策略</th>
                <th className="text-left px-4 py-2.5 font-medium">市场</th>
                <th className="text-left px-4 py-2.5 font-medium">状态</th>
                <th className="text-left px-4 py-2.5 font-medium">创建时间</th>
                <th className="text-right px-4 py-2.5 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {portfolios.map((p) => {
                const meta = STATUS_META[p.status] || STATUS_META.running
                return (
                  <tr
                    key={p.id}
                    className="border-t border-border hover:bg-muted/30 cursor-pointer transition-colors"
                    onClick={() => navigate(`/paper/${p.id}`)}
                  >
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{p.strategy_name}</td>
                    <td className="px-4 py-3">
                      <span className="text-xs px-1.5 py-0.5 rounded bg-muted">{p.market}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('text-xs font-medium', meta.class)}>{meta.label}</span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs font-mono">
                      {p.created_at ? new Date(p.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex justify-end gap-1">
                        {p.status === 'running' && (
                          <button
                            onClick={() => handleAction(p.id, 'pause')}
                            className="p-1 rounded hover:bg-accent"
                            title="暂停"
                          >
                            <Pause className="h-3.5 w-3.5 text-yellow-500" />
                          </button>
                        )}
                        {p.status === 'paused' && (
                          <button
                            onClick={() => handleAction(p.id, 'resume')}
                            className="p-1 rounded hover:bg-accent"
                            title="恢复"
                          >
                            <Play className="h-3.5 w-3.5 text-green-500" />
                          </button>
                        )}
                        {p.status !== 'closed' && (
                          <button
                            onClick={() => handleAction(p.id, 'close')}
                            className="p-1 rounded hover:bg-accent"
                            title="关闭"
                          >
                            <XCircle className="h-3.5 w-3.5 text-red-500" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Dialog */}
      {showCreate && (
        <CreatePortfolioDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            fetchPortfolios()
          }}
        />
      )}
    </div>
  )
}
