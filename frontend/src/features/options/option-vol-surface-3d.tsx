import { useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE_URL } from '@/lib/constants'
import type { VolMatrix } from './option-vol-surface'

type LegType = 'call' | 'put'

/** 低波绿 → 高波红 的连续色阶 (与 2D 热力图一致) */
function ivColor(iv: number | null | undefined, min: number, max: number): string {
  if (iv == null || !isFinite(iv)) return 'rgba(148,163,184,0.25)'
  const t = max > min ? (iv - min) / (max - min) : 0.5
  const hue = 160 - 160 * Math.min(Math.max(t, 0), 1)
  return `hsl(${hue}, 65%, 52%)`
}

function mmdd(d: string): string {
  return d.length >= 10 ? d.slice(5) : d
}

export function OptionVolSurface3D({ symbol }: { symbol: string }) {
  const [type, setType] = useState<LegType>('call')
  const [data, setData] = useState<VolMatrix | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [yaw, setYaw] = useState(-0.7)
  const [pitch, setPitch] = useState(0.55)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const dragRef = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(
      `${API_BASE_URL}/options/chain-matrix/${encodeURIComponent(symbol)}?max_expiries=8&max_strikes=21`,
      { credentials: 'include' },
    )
      .then((r) => {
        if (!r.ok) {
          return r.json().then((err) => {
            throw new Error(err?.detail || `HTTP ${r.status}`)
          })
        }
        return r.json()
      })
      .then((j) => {
        if (!cancelled) setData(j)
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

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data || !data.expirations?.length) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const W = canvas.clientWidth
    const H = canvas.clientHeight
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)

    const grid = type === 'call' ? data.calls.iv : data.puts.iv
    const E = data.expirations.length
    const S = data.strikes.length
    const cx = W / 2
    const cy = H / 2 + 20

    const sx = 26
    const sz = 34
    const sy = (H * 0.32) / Math.max(1, max - min || 1)

    // 构建 3D 点 (x: strike, z: expiry, y: iv 高度)
    const pts: { x: number; y: number; z: number; iv: number; valid: boolean }[][] = []
    for (let i = 0; i < E; i++) {
      const row: { x: number; y: number; z: number; iv: number; valid: boolean }[] = []
      for (let k = 0; k < S; k++) {
        const iv = grid[i]?.[k]
        const x = (k - (S - 1) / 2) * sx
        const z = (i - (E - 1) / 2) * sz
        const y = ((iv ?? min) - (min + max) / 2) * sy
        row.push({ x, y, z, iv: iv ?? NaN, valid: iv != null && isFinite(iv) })
      }
      pts.push(row)
    }

    const cosY = Math.cos(yaw)
    const sinY = Math.sin(yaw)
    const cosP = Math.cos(pitch)
    const sinP = Math.sin(pitch)

    const project = (p: { x: number; y: number; z: number }) => {
      const x1 = p.x * cosY - p.z * sinY
      const z1 = p.x * sinY + p.z * cosY
      const y1 = p.y * cosP - z1 * sinP
      const z2 = p.y * sinP + z1 * cosP
      const scale = 1
      return {
        sx: cx + x1 * scale,
        sy: cy - y1 * scale - z2 * scale * 0.35,
        depth: z2,
      }
    }

    // 1) 画网格线 (沿 expiry 方向的连线)
    ctx.lineWidth = 1
    for (let k = 0; k < S; k++) {
      ctx.beginPath()
      let started = false
      for (let i = 0; i < E; i++) {
        const p = pts[i][k]
        const pr = project(p)
        if (!started) {
          ctx.moveTo(pr.sx, pr.sy)
          started = true
        } else {
          ctx.lineTo(pr.sx, pr.sy)
        }
      }
      ctx.strokeStyle = 'rgba(139,92,246,0.28)'
      ctx.stroke()
    }
    // 2) 画网格线 (沿 strike 方向的连线)
    for (let i = 0; i < E; i++) {
      ctx.beginPath()
      let started = false
      for (let k = 0; k < S; k++) {
        const p = pts[i][k]
        const pr = project(p)
        if (!started) {
          ctx.moveTo(pr.sx, pr.sy)
          started = true
        } else {
          ctx.lineTo(pr.sx, pr.sy)
        }
      }
      ctx.strokeStyle = 'rgba(59,130,246,0.22)'
      ctx.stroke()
    }

    // 3) 画顶点 (按深度排序, 远→近)
    const dots: { pr: { sx: number; sy: number; depth: number }; iv: number; valid: boolean }[] = []
    for (let i = 0; i < E; i++) {
      for (let k = 0; k < S; k++) {
        const p = pts[i][k]
        dots.push({ pr: project(p), iv: p.iv, valid: p.valid })
      }
    }
    dots.sort((a, b) => b.pr.depth - a.pr.depth)
    for (const d of dots) {
      if (!d.valid) continue
      ctx.beginPath()
      ctx.arc(d.pr.sx, d.pr.sy, 3.2, 0, Math.PI * 2)
      ctx.fillStyle = ivColor(d.iv, min, max)
      ctx.fill()
    }
  }, [data, type, yaw, pitch, min, max])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载 3D 波动率曲面…</div>
  if (error) return <div className="p-6 text-sm text-red-400">期权数据获取失败：{error}</div>
  if (!data || !data.expirations?.length)
    return <div className="p-6 text-sm text-slate-400">该标的暂无期权数据</div>

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-border/60 p-0.5">
          {(['call', 'put'] as LegType[]).map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={
                'rounded-md px-3 py-1 text-xs font-medium transition-colors ' +
                (type === t
                  ? 'bg-primary text-primary-foreground'
                  : 'text-slate-400 hover:text-slate-200')
              }
            >
              {t === 'call' ? '看涨 CALL' : '看跌 PUT'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span>低</span>
          <span
            className="h-3 w-28 rounded"
            style={{
              background:
                'linear-gradient(90deg, hsl(160,65%,42%), hsl(80,65%,42%), hsl(0,65%,42%))',
            }}
          />
          <span>高 IV</span>
          <span className="ml-2 text-slate-500">
            {min.toFixed(1)}% – {max.toFixed(1)}%
          </span>
        </div>
      </div>

      <div
        className="relative w-full overflow-hidden rounded-lg border border-border/40 bg-card/30"
        style={{ height: 420 }}
        onMouseDown={(e) => {
          dragRef.current = { x: e.clientX, y: e.clientY }
        }}
        onMouseUp={() => {
          dragRef.current = null
        }}
        onMouseLeave={() => {
          dragRef.current = null
        }}
        onMouseMove={(e) => {
          if (!dragRef.current) return
          const dx = e.clientX - dragRef.current.x
          const dy = e.clientY - dragRef.current.y
          dragRef.current = { x: e.clientX, y: e.clientY }
          setYaw((v) => v + dx * 0.01)
          setPitch((v) => Math.max(-1.2, Math.min(1.2, v + dy * 0.01)))
        }}
      >
        <canvas ref={canvasRef} className="h-full w-full cursor-grab active:cursor-grabbing" />
        <div className="pointer-events-none absolute bottom-2 left-3 text-[10px] text-slate-500">
          拖拽旋转 · {type === 'call' ? 'CALL' : 'PUT'} IV 曲面（X=行权价, Z=到期, Y=IV）
        </div>
      </div>

      <div className="text-[11px] text-slate-500">
        到期序列：{data.expirations.map(mmdd).join(' · ')}
      </div>
    </div>
  )
}
