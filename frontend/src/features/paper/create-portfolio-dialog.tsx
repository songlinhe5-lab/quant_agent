/**
 * PT-02b: 创建纸面组合表单
 */
'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface CreatePortfolioDialogProps {
  onClose: () => void
  onCreated: () => void
}

export function CreatePortfolioDialog({ onClose, onCreated }: CreatePortfolioDialogProps) {
  const [name, setName] = useState('')
  const [strategyName, setStrategyName] = useState('')
  const [codeHash, setCodeHash] = useState('')
  const [market, setMarket] = useState<'HK' | 'US'>('HK')
  const [initialCapital, setInitialCapital] = useState(100000)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !strategyName || !codeHash) {
      setError('请填写必填字段')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await apiClient.post('/paper/portfolios', {
        name,
        strategy_name: strategyName,
        code_hash: codeHash,
        market,
        initial_capital: initialCapital,
      })
      onCreated()
    } catch {
      setError('创建失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-lg">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">创建纸面组合</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-accent">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="text-sm text-red-500 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-sm font-medium">组合名称 *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：腾讯动量策略"
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              maxLength={64}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">策略名称 *</label>
            <input
              type="text"
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              placeholder="如：momentum_v2"
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              maxLength={64}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">代码 Hash *</label>
            <input
              type="text"
              value={codeHash}
              onChange={(e) => setCodeHash(e.target.value)}
              placeholder="策略代码 SHA256"
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary font-mono"
              maxLength={64}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">市场</label>
              <select
                value={market}
                onChange={(e) => setMarket(e.target.value as 'HK' | 'US')}
                className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="HK">港股 HK</option>
                <option value="US">美股 US</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">初始资金</label>
              <input
                type="number"
                value={initialCapital}
                onChange={(e) => setInitialCapital(Number(e.target.value))}
                className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary font-mono"
                min={1000}
                step={10000}
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-md border border-border hover:bg-accent transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {submitting ? '创建中...' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
