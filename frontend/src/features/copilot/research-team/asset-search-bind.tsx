/**
 * 标的搜索绑定：输入名称/代码 → /market/search 联想 → 选择绑定 ticker。
 * 投研会用于显式指定分析标的（使 quote/fundamental/technicals 数据可采集）。
 * 复用 /market/search 统一模糊匹配底层。
 */
'use client'

import React, { useEffect, useRef, useState } from 'react'
import { Search, TrendingUp, Landmark, LineChart, X } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface SearchItem {
  symbol?: string
  code?: string
  name?: string
  type?: string
}

export function AssetSearchBind({
  value,
  onChange,
}: {
  /** 当前绑定的 ticker（标准格式，如 US.AAPL） */
  value: string
  onChange: (ticker: string, name: string) => void
}) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [results, setResults] = useState<SearchItem[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [boundName, setBoundName] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    if (!debounced.trim()) {
      setResults([])
      setOpen(false)
      return
    }
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setOpen(true)
      try {
        const res = await apiClient.get('/market/search', { q: debounced.trim() })
        const payload = res?.data
        if (!cancelled && payload && Array.isArray(payload.data)) setResults(payload.data)
        else if (!cancelled) setResults([])
      } catch {
        if (!cancelled) setResults([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [debounced])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const icon = (type?: string) => {
    switch (type?.toUpperCase()) {
      case 'EQUITY':
      case 'STOCK':
        return <TrendingUp className="h-3.5 w-3.5 text-blue-400" />
      case 'ETF':
        return <Landmark className="h-3.5 w-3.5 text-purple-400" />
      case 'INDEX':
        return <LineChart className="h-3.5 w-3.5 text-emerald-400" />
      default:
        return <TrendingUp className="h-3.5 w-3.5 text-slate-400" />
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      {/* 已绑定标的 */}
      {value ? (
        <div className="flex items-center gap-2 rounded-lg border border-scene/40 bg-scene/10 px-2.5 py-1.5 text-[11px]">
          <span className="font-mono font-bold text-scene">{value}</span>
          {boundName && <span className="text-muted-foreground">{boundName}</span>}
          <button
            type="button"
            onClick={() => {
              onChange('', '')
              setQuery('')
              setBoundName('')
            }}
            className="ml-auto flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            title="解除绑定"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索并绑定标的（如 阅文集团 / AAPL）"
              className="w-full rounded-lg border border-white/10 bg-black/30 py-1.5 pl-8 pr-2.5 text-[11px] text-foreground placeholder:text-muted-foreground/50 focus:border-scene/50 focus:outline-none"
            />
          </div>
          {open && (
            <div className="absolute z-30 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border border-white/10 bg-[#0b0f17] shadow-lg">
              {loading && <div className="px-3 py-2 text-[10px] text-muted-foreground">搜索中…</div>}
              {!loading && results.length === 0 && (
                <div className="px-3 py-2 text-[10px] text-muted-foreground/60">未找到匹配标的</div>
              )}
              {results.map((r, i) => {
                const code = r.code || r.symbol || ''
                return (
                  <button
                    key={`${code}-${i}`}
                    type="button"
                    onClick={() => {
                      onChange(code, r.name || '')
                      setBoundName(r.name || '')
                      setOpen(false)
                      setQuery('')
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] hover:bg-white/5"
                  >
                    {icon(r.type)}
                    <span className="font-mono font-bold text-foreground/90">{code}</span>
                    <span className="truncate text-muted-foreground">{r.name}</span>
                    {r.type && <span className="ml-auto text-[9px] uppercase text-muted-foreground/50">{r.type}</span>}
                  </button>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
