import { CapitalFlowPanel } from '@/features/data-center/capital-flow'
import { SectorFlowPanel, type SectorFundFlowData } from '@/features/data-center/sector-flow'
import { SectorHeatmapPanel } from '@/features/data-center/sector-heatmap-panel'
import { MarketSnapshotPanel } from '@/features/data-center/market-snapshot-panel'
import { OrderBookPanel } from '@/features/data-center/order-book-panel'
import { CapitalDistributionPanel } from '@/features/data-center/capital-distribution-panel'
import { StockBasicInfoPanel } from '@/features/data-center/stock-basicinfo-panel'
import { MarginTradingPanel } from '@/features/data-center/margin-trading'
import { ShortSellingPanel } from '@/features/data-center/short-selling-panel'
import type { useDashboardData as useDashboardDataType, HubTab } from '@/features/data-center/use-dashboard-data'

interface Props {
  data: ReturnType<typeof useDashboardDataType>
  onNavigate: (tab: HubTab, symbol?: string) => void
}

export function CapitalFlowTab({ data, onNavigate }: Props) {
  void onNavigate
  const {
    capitalFlows, sectorFlowData, sectorFlowStatus, marginData, marginStatus,
    last, shortSellingHasContent,
  } = data

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <CapitalFlowPanel data={capitalFlows} />
        {sectorFlowData && <SectorFlowPanel data={sectorFlowData} status={sectorFlowStatus} />}
      </div>

      <SectorHeatmapPanel market="US" />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <MarketSnapshotPanel tickers="HK.00700,US.AAPL,HK.09988,US.NVDA,US.TSLA" />
        <OrderBookPanel ticker="HK.00700" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <CapitalDistributionPanel ticker="HK.00700" />
        <StockBasicInfoPanel market="HK" secType="STOCK" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <MarginTradingPanel data={marginData} status={marginStatus} lastUpdated={last} />
        <ShortSellingPanel ticker="HK.00700" mode="overview" />
      </div>
    </div>
  )
}
