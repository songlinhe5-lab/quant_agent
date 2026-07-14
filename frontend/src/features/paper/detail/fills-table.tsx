/**
 * PT-02b: 成交流水表格
 */
'use client'

import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'

interface Fill {
  id: string
  fill_seq: number
  dt: string
  symbol: string
  side: string
  qty: number
  price: number
  commission: number
  slippage: number
  intent_tag: string | null
}

interface FillsTableProps {
  portfolioId: string
}

const PAGE_SIZE = 20

export function FillsTable({ portfolioId }: FillsTableProps) {
  const [fills, setFills] = useState<Fill[]>([])
  const [loading, setLoading] = useState(true)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient
      .get<any>(`/paper/portfolios/${portfolioId}/fills`, {
        limit: PAGE_SIZE,
        offset,
      })
      .then((res) => {
        const data = res.data?.data || []
        setFills(data)
        setHasMore(data.length === PAGE_SIZE)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [portfolioId, offset])

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">成交流水</h3>
      {loading ? (
        <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">加载中...</div>
      ) : fills.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">暂无成交记录</div>
      ) : (
        <>
          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left px-3 py-2 font-medium text-xs">#</th>
                  <th className="text-left px-3 py-2 font-medium text-xs">时间</th>
                  <th className="text-left px-3 py-2 font-medium text-xs">标的</th>
                  <th className="text-left px-3 py-2 font-medium text-xs">方向</th>
                  <th className="text-right px-3 py-2 font-medium text-xs">数量</th>
                  <th className="text-right px-3 py-2 font-medium text-xs">价格</th>
                  <th className="text-right px-3 py-2 font-medium text-xs">手续费</th>
                  <th className="text-left px-3 py-2 font-medium text-xs">标签</th>
                </tr>
              </thead>
              <tbody>
                {fills.map((f) => (
                  <tr key={f.id} className="border-t border-border">
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{f.fill_seq}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {f.dt ? new Date(f.dt).toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2 font-medium">{f.symbol}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          'text-xs font-medium px-1.5 py-0.5 rounded',
                          f.side === 'BUY' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'
                        )}
                      >
                        {f.side === 'BUY' ? '买' : '卖'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{f.qty}</td>
                    <td className="px-3 py-2 text-right font-mono">{f.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">{f.commission.toFixed(2)}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{f.intent_tag || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0}
              className="px-2 py-1 rounded hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed"
            >
              上一页
            </button>
            <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={!hasMore}
              className="px-2 py-1 rounded hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed"
            >
              下一页
            </button>
          </div>
        </>
      )}
    </div>
  )
}
