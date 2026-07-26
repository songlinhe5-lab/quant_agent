import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { API_BASE_URL } from '@/lib/constants'
import { cn } from '@/lib/utils'

export interface VolMatrix {
  status: string
  symbol: string
  underlying_price: number
  expirations: string[]
  strikes: number[]
  calls: { iv: number[][]; delta: number[][] }
  puts: { iv: number[][]; delta: number[][] }
  legs: { type: string; expiry: string; strike: number; iv: number; delta: number }[]
  source?: string
}

type LegType = 'call' | 'put'

/** 低波绿 → 高波红 的连续色阶 */
function ivColor(iv: number | null | undefined, min: number, max: number): string {
  if (iv == null || !isFinite(iv)) return 'transparent'
  const t = max > min ? (iv - min) / (max - min) : 0.5
  const hue = 160 - 160 * Math.min(Math.max(t, 0), 1) // 160(绿) -> 0(红)
  return `hsl(${hue}, 65%, 42%)`
}

function mmdd(d: string): string {
  return d.length >= 10 ? d.slice(5) : d
}

export function OptionVolSurface({ symbol }: { symbol: string }) {
  const [type, setType] = useState<LegType>('call')
  const [data, setData] = useState<VolMatrix | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ expiry: string; strike: number } | null>(null)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(
      `${API_BASE_URL}/options/chain-matrix/${encodeURIComponent(symbol)}?max_expiries=8&max_strikes=21`,
      { credentials: 'include' },
    )
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled) {
          setData(j)
          setSelected(null)
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [symbol])

  const { min, max } = useMemo(() => {
    if (!data) return { min: 0, max: 1 }
    const arr = (type === 'call' ? data.calls.iv : data.puts.iv)
      .flat()
      .filter((v) => v != null && isFinite(v))
    if (!arr.length) return { min: 0, max: 1 }
    return { min: Math.min(...arr), max: Math.max(...arr) }
  }, [data, type])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载波动率曲面…</div>
  if (error)
    return <div className="p-6 text-sm text-red-400">期权数据获取失败：{error}</div>
  if (!data || !data.expirations?.length)
    return <div className="p-6 text-sm text-slate-400">该标的暂无期权数据</div>

  const grid = type === 'call' ? data.calls.iv : data.puts.iv
  const atmStrike = data.underlying_price
  const nearestStrike =
    data.strikes.reduce(
      (best, s) => (Math.abs(s - atmStrike) < Math.abs(best - atmStrike) ? s : best),
      data.strikes[0],
    )
  const selectedLeg = selected
    ? data.legs.find(
        (l) =>
          l.type === type &&
          l.expiry === selected.expiry &&
          Math.abs(l.strike - selected.strike) < 1e-6,
      )
    : undefined
  const colCount = data.expirations.length

  return (
    <div className="flex flex-col gap-3">
      {/* 控制栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-border/60 p-0.5">
          {(['call', 'put'] as LegType[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setType(t)
                setSelected(null)
              }}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                type === t
                  ? 'bg-primary text-primary-foreground'
                  : 'text-slate-400 hover:text-slate-200',
              )}
            >
              {t === 'call' ? '看涨 CALL' : '看跌 PUT'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span>低</span>
          <span
            className="h-3 w-28 rounded"
            style={{ background: 'linear-gradient(90deg, hsl(160,65%,42%), hsl(80,65%,42%), hsl(0,65%,42%))' }}
          />
          <span>高 IV</span>
          <span className="ml-2 text-slate-500">
            {min.toFixed(1)}% – {max.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* 热力图（行列网格） */}
      <div className="overflow-x-auto">
        <div
          className="grid min-w-max text-center text-[11px]"
          style={{ gridTemplateColumns: `64px repeat(${colCount}, minmax(56px, 1fr))` }}
        >
          {/* 表头：到期日 */}
          <div className="sticky left-0 z-10 bg-card/80 px-2 py-1 text-left text-slate-500">
            行权价 \ 到期
          </div>
          {data.expirations.map((exp) => (
            <div key={exp} className="px-1 py-1 font-medium text-slate-300">
              {mmdd(exp)}
            </div>
          ))}

          {/* 每行：行权价 + IV 单元格 */}
          {data.strikes.map((strike, k) => {
            const isAtm = Math.abs(strike - nearestStrike) < 1e-6
            return (
              <RowFragment key={strike}>
                <div
                  className={cn(
                    'sticky left-0 z-10 bg-card/80 px-2 py-1 text-right tabular-nums',
                    isAtm ? 'font-semibold text-emerald-300' : 'text-slate-400',
                  )}
                >
                  {strike}
                </div>
                {data.expirations.map((exp, i) => {
                  const iv = grid[i]?.[k]
                  const isSel =
                    selected && selected.expiry === exp && Math.abs(selected.strike - strike) < 1e-6
                  return (
                    <button
                      key={exp}
                      onClick={() => setSelected({ expiry: exp, strike })}
                      title={`${type.toUpperCase()} ${exp} K=${strike} IV=${iv?.toFixed(1)}%`}
                      className={cn(
                        'h-7 border border-black/10 tabular-nums text-white/95 transition-transform',
                        isSel && 'outline outline-2 outline-white',
                      )}
                      style={{ background: ivColor(iv, min, max) }}
                    >
                      {iv != null && isFinite(iv) ? iv.toFixed(1) : '–'}
                    </button>
                  )
                })}
              </RowFragment>
            )
          })}
        </div>
      </div>

      {/* 选中单元格明细 */}
      <div className="rounded-lg border border-border/50 bg-card/40 px-4 py-3 text-xs">
        {selectedLeg ? (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-slate-300">
            <span className="font-medium text-slate-100">
              {type.toUpperCase()} · 到期 {mmdd(selectedLeg.expiry)} · 行权价 {selectedLeg.strike}
            </span>
            <span>IV <b className="text-emerald-300">{selectedLeg.iv?.toFixed(2)}%</b></span>
            <span>Delta <b className="text-sky-300">{selectedLeg.delta?.toFixed(3)}</b></span>
            <span className="text-slate-500">
              ATM 参考 {atmStrike?.toFixed(2)}
            </span>
          </div>
        ) : (
          <span className="text-slate-500">点击单元格查看 IV / Delta 明细</span>
        )}
      </div>
    </div>
  )
}

/** 表格行包装：用 fragment 渲染行内的多个 grid 单元 */
function RowFragment({ children }: { children: ReactNode }) {
  return <>{children}</>
}
