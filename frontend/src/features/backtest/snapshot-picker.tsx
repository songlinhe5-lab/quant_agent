'use client'

import { Database } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDatalakeSnapshots } from '@/hooks/use-datalake-snapshots'
import { LATEST_PUBLISHED, LIVE_SNAPSHOT } from '@/types/datalake'

type SnapshotPickerProps = {
  value: string
  onChange: (snapshotId: string) => void
  disabled?: boolean
  className?: string
  /** 允许选择 live（开发降级）；默认 false，仅 latest_published + published 列表 */
  allowLive?: boolean
}

/**
 * 回测参数区「数据快照 ▾」选择器（docs/01 §5.0 · FE-PROD-04）
 */
export function SnapshotPicker({
  value,
  onChange,
  disabled,
  className,
  allowLive = false,
}: SnapshotPickerProps) {
  const { snapshots, latest, loading, error } = useDatalakeSnapshots(true)

  return (
    <div className={cn('min-w-0', className)} data-testid="snapshot-picker">
      <p className="text-[10px] text-muted-foreground mb-1 flex items-center gap-1">
        <Database className="h-3 w-3" aria-hidden />
        数据快照
        {latest?.stale_warning && (
          <span className="text-amber-500 font-mono">STALE ≥3d</span>
        )}
      </p>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || loading}
        aria-label="选择数据快照"
        className="bg-background border border-border/50 rounded px-2 py-1.5 text-xs outline-none focus:border-primary w-full cursor-pointer font-mono"
      >
        <option value={LATEST_PUBLISHED}>
          latest_published
          {latest?.snapshot_id ? ` → ${latest.snapshot_id}` : ''}
        </option>
        {allowLive && <option value={LIVE_SNAPSHOT}>live（不可复现）</option>}
        {snapshots.map((s) => (
          <option key={s.snapshot_id} value={s.snapshot_id}>
            {s.snapshot_id}
            {s.as_of_date ? ` · ${s.as_of_date}` : ''}
            {s.is_monthly_anchor ? ' · 月锚' : ''}
          </option>
        ))}
      </select>
      {error && (
        <p className="text-[9px] text-amber-500 mt-0.5">快照列表不可用，将使用 {LATEST_PUBLISHED}</p>
      )}
      {!loading && !error && snapshots.length === 0 && (
        <p className="text-[9px] text-slate-500 mt-0.5">暂无 published 快照，运行时解析 latest_published</p>
      )}
    </div>
  )
}
