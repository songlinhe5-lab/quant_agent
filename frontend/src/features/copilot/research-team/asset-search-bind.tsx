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
  const [errored, setErrored] = useState(false)
  const [boundName, setBoundName] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  // 竞态保护：只采纳最新一次请求的结果（避免慢请求覆盖快请求导致联想闪烁/时有时无）
  const reqIdRef = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    const term = debounced.trim()
    if (!term) {
      setResults([])
      setOpen(false)
      setErrored(false)
      return
    }
    const reqId = ++reqIdRef.current
    setLoading(true)
    setOpen(true)
    setErrored(false)
    const run = async () => {
      try {
        const res = await apiClient.get('/market/search', { q: term })
        if (reqId !== reqIdRef.current) return // 已有更新的请求，丢弃本次结果
        const payload = res?.data
        if (payload && Array.isArray(payload.data)) setResults(payload.data)
        else setResults([])
      } catch {
        if (reqId !== reqIdRef.current) return
        setResults([])
        setErrored(true) // 后端失败时显式提示，而非静默空结果
      } finally {
        if (reqId === reqIdRef.current) setLoading(false)
      }
    }
    run()
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

  // 回车兜底绑定：联想不可用 / 本地词库无命中时，用户可直接回车绑定已输入文本
  const bindByText = async (raw: string) => {
    const text = raw.trim()
    if (!text) return
    // 1. 若下拉已有精确匹配（输入即命中第一项），优先用其标准代码
    const exact = results.find((r) => {
      const code = (r.code || r.symbol || '').toUpperCase()
      return code === text.toUpperCase() || (r.name || '').toUpperCase() === text.toUpperCase()
    })
    if (exact) {
      const code = exact.code || exact.symbol || ''
      onChange(code, exact.name || '')
      setBoundName(exact.name || '')
      setOpen(false)
      setQuery('')
      return
    }
    // 2. 尝试后端解析一次（兼容 中文名/代码 → 标准 ticker）
    try {
      const res = await apiClient.get('/market/search', { q: text })
      const payload = res?.data
      if (payload && Array.isArray(payload.data) && payload.data.length > 0) {
        const hit = payload.data[0]
        const code = hit.code || hit.symbol || ''
        if (code) {
          onChange(code, hit.name || text)
          setBoundName(hit.name || '')
          setOpen(false)
          setQuery('')
          return
        }
      }
    } catch {
      /* 后端不可用则直接透传原始文本 */
    }
    // 3. 仍无结果 → 直接把原始文本作为 ticker 绑定（后续解析链兜底）
    onChange(text, text)
    setBoundName(text)
    setOpen(false)
    setQuery('')
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
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  bindByText(query)
                } else if (e.key === 'Escape') {
                  setOpen(false)
                }
              }}
              placeholder="搜索并绑定标的（如 阅文集团 / AAPL），回车直接绑定"
              className="w-full rounded-lg border border-white/10 bg-black/30 py-1.5 pl-8 pr-2.5 text-[11px] text-foreground placeholder:text-muted-foreground/50 focus:border-scene/50 focus:outline-none"
            />
          </div>
          {open && (
            <div className="absolute z-30 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border border-white/10 bg-[#0b0f17] shadow-lg">
              {loading && <div className="px-3 py-2 text-[10px] text-muted-foreground">搜索中…</div>}
              {!loading && errored && (
                <div className="px-3 py-2 text-[10px] text-amber-400/80">搜索服务暂不可用，回车直接绑定代码（如 US.AAPL）</div>
              )}
              {!loading && !errored && results.length === 0 && (
                <div className="px-3 py-2 text-[10px] text-muted-foreground/60">未找到匹配标的，回车直接绑定</div>
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
