import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Card, CardHeader } from './data-center-capital-flow'

const fmtYi = (v: number) => {
  if (v == null || Number.isNaN(v)) return '—'
  const yi = v / 1e8
  return `${yi >= 0 ? '+' : ''}${yi.toFixed(2)}亿`
}

function LhbTable({ title, rows, accent }: { title: string; rows: any[]; accent: string }) {
  if (!rows || rows.length === 0) {
    return (
      <Card>
        <CardHeader title={title} />
        <div className="flex flex-col items-center justify-center gap-1 p-5 text-center">
          <AlertTriangle className="h-4 w-4 text-muted-foreground/40" />
          <p className="text-[11px] text-muted-foreground">{title}暂无数据</p>
        </div>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader title={title} sub={`${rows.length} 只`} />
      <div className="flex flex-col divide-y divide-border/30">
        {rows.map((r, i) => (
          <div key={r.code || i} className="flex items-center justify-between px-3 py-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-foreground truncate">{r.name}</span>
                <span className="text-[10px] text-muted-foreground">{r.code}</span>
              </div>
              {r.reason && (
                <span className={cn('text-[10px]', accent)}>{r.reason}</span>
              )}
            </div>
            <div className="text-right">
              <div className={cn('text-xs font-semibold', (r.period_net_buy ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                {fmtYi(r.period_net_buy)}
              </div>
              <div className="text-[10px] text-muted-foreground/60">当日 {fmtYi(r.net_buy)}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function DragonTigerBoard({ data, status }: { data?: any; status?: string }) {
  const hasData = !!data && (Array.isArray(data.institution) || Array.isArray(data.retail))
  return (
    <section>
      <div className="flex items-center gap-2 px-1">
        <span className="text-sm font-semibold text-foreground">龙虎榜 · 机构 vs 游资</span>
        {data?.trade_date && (
          <span className="text-[10px] text-muted-foreground">交易日 {data.trade_date}</span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground/60">{data?.unit || '元'}</span>
      </div>
      {hasData ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-2.5">
          <LhbTable title="机构净买榜" rows={data.institution} accent="text-sky-400" />
          <LhbTable title="游资净买榜" rows={data.retail} accent="text-amber-400" />
        </div>
      ) : (
        <Card className="mt-2.5">
          <div className="flex flex-col items-center justify-center gap-1 p-8 text-center">
            <AlertTriangle className="h-5 w-5 text-muted-foreground/40" />
            <p className="text-[11px] text-muted-foreground">龙虎榜数据未接入</p>
            <p className="text-[10px] text-muted-foreground/60">
              接入 AKShare 龙虎榜（机构/游资）后，此处展示近区间净买额排序。
            </p>
          </div>
        </Card>
      )}
    </section>
  )
}
