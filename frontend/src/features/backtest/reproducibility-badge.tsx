'use client'

import { CheckCircle2, XCircle, Fingerprint } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ReproducibilityBadge } from '@/types/datalake'

type Props = {
  badge?: ReproducibilityBadge | null
  className?: string
}

function shortHash(h: string | null | undefined, n = 12): string {
  if (!h) return '—'
  return h.length <= n ? h : h.slice(0, n)
}

/**
 * 报告页可复现性徽章：code_hash · manifest_hash · reproducible
 */
export function ReproducibilityBadgeView({ badge, className }: Props) {
  if (!badge) return null

  const ok = Boolean(badge.reproducible)

  return (
    <div
      data-testid="reproducibility-badge"
      className={cn(
        'inline-flex flex-wrap items-center gap-2 rounded-md border px-2.5 py-1.5 text-[10px] font-mono',
        ok
          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
          : 'border-amber-500/40 bg-amber-500/10 text-amber-500',
        className,
      )}
      title={
        ok
          ? '同 code_hash + manifest_hash + seed 可复现'
          : '未绑定完整快照指纹或未固定种子 — 非正式可复现'
      }
    >
      <Fingerprint className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {ok ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" aria-hidden />
      ) : (
        <XCircle className="h-3.5 w-3.5 text-amber-500 shrink-0" aria-hidden />
      )}
      <span className="font-bold tracking-wide">
        {ok ? 'REPRODUCIBLE' : 'NON-REPRODUCIBLE'}
      </span>
      <span className="text-slate-500">|</span>
      <span>
        code <span className="text-foreground/90">{shortHash(badge.code_hash)}</span>
      </span>
      <span className="text-slate-500">|</span>
      <span>
        manifest <span className="text-foreground/90">{shortHash(badge.manifest_hash)}</span>
      </span>
      {badge.data_snapshot_id && (
        <>
          <span className="text-slate-500">|</span>
          <span className="truncate max-w-[140px]" title={badge.data_snapshot_id}>
            {badge.data_snapshot_id}
          </span>
        </>
      )}
    </div>
  )
}

/** 从回测响应 data 提取徽章（兼容 manifest / badge 两种字段） */
export function extractReproducibilityBadge(data: unknown): ReproducibilityBadge | null {
  if (!data || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (d.badge && typeof d.badge === 'object') {
    const b = d.badge as Record<string, unknown>
    return {
      code_hash: String(b.code_hash || ''),
      manifest_hash: b.manifest_hash ? String(b.manifest_hash) : null,
      reproducible: Boolean(b.reproducible),
      data_snapshot_id: b.data_snapshot_id ? String(b.data_snapshot_id) : undefined,
      data_mode: b.data_mode ? String(b.data_mode) : undefined,
    }
  }
  if (d.manifest && typeof d.manifest === 'object') {
    const m = d.manifest as Record<string, unknown>
    return {
      code_hash: String(m.code_hash || ''),
      manifest_hash: m.manifest_hash ? String(m.manifest_hash) : null,
      reproducible: Boolean(m.reproducible),
      data_snapshot_id: m.data_snapshot_id ? String(m.data_snapshot_id) : undefined,
      data_mode: m.data_mode ? String(m.data_mode) : undefined,
    }
  }
  return null
}
