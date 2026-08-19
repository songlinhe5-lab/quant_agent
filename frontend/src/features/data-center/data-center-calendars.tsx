import { CalendarsModule } from '@/features/calendars/module'
import { MacroChartPanel } from '@/features/data-center/macro-chart'
import { NewsStream } from '@/features/data-center/news-stream'
import { FedWatchPanel } from '@/features/options/fed-watch-panel'
import type { useDashboardData as useDashboardDataType } from '@/features/data-center/use-dashboard-data'

interface Props {
  data: ReturnType<typeof useDashboardDataType>
}

export function CalendarsTab({ data }: Props) {
  const { news, visibleNewsCount, setVisibleNewsCount } = data
  return (
    <div className="flex flex-col gap-4">
      <CalendarsModule />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <MacroChartPanel />
        <FedWatchPanel />
      </div>
      <div className="glass-card p-4">
        <h3 className="text-sm font-semibold text-foreground mb-3">财经快讯 · 实时流</h3>
        <NewsStream
          news={news}
          visibleNewsCount={visibleNewsCount}
          setVisibleNewsCount={setVisibleNewsCount}
        />
      </div>
    </div>
  )
}
