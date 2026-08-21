import { useMemo } from 'react'
import { ChevronDown, ChevronRight, ArrowRightLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CapitalDistributionPanel } from '@/features/data-center/capital-distribution-panel'
import { AnalystVsFundamentalPanel } from '@/features/data-center/analyst-vs-fundamental-panel'
import { ShortSellingPanel } from '@/features/data-center/short-selling-panel'
import { StockBasicInfoPanel } from '@/features/data-center/stock-basicinfo-panel'
import { CapitalFlowPanel } from '@/features/quotes/capital-flow-panel'
import { toMarketSymbol, isHkMarket } from './symbol-utils'
import { useNavigate } from 'react-router-dom'

/**
 * 个股工作台 · 右栏 [盘口 | 微观] 的「微观」tab。
 * 迁入自 data-center 的个股微观面板，以自选池选中标的为参数（Figma Frame 4 右栏）。
 * - 主力筹码分层 / 卖方共识 vs 基本面：全市场
 * - 卖空拥挤度：仅港股标的显示
 * - 基础信息：默认折叠
 */
export function MicroPanel({ symbol }: { symbol: string }) {
  const futu = useMemo(() => toMarketSymbol(symbol), [symbol])
  const hk = useMemo(() => isHkMarket(symbol), [symbol])
  const navigate = useNavigate()

  // UIRF-20: 所属板块跳转资金流向页面
  const goToSectorCapitalFlow = () => {
    navigate(`/data-center/capital-flow?ticker=${encodeURIComponent(symbol)}`)
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto custom-scrollbar p-2">
      {/* 所属板块快速入口（UIRF-20） */}
      <button
        onClick={goToSectorCapitalFlow}
        className="glass-card rounded-lg overflow-hidden hover:border-primary/40 transition-colors cursor-pointer group"
      >
        <div className="px-3 py-2.5 border-b border-border/30 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ArrowRightLeft className="h-3.5 w-3.5 text-sky-500 dark:text-sky-400" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">所属板块资金流向</span>
          </div>
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 group-hover:text-foreground transition-transform" />
        </div>
        <div className="p-3 text-[10px] text-muted-foreground/60">
          查看该股所属行业板块的主力资金分布与净流入情况
        </div>
      </button>

      <CapitalDistributionPanel ticker={futu} />
      <CapitalFlowPanel symbol={futu} />
      <AnalystVsFundamentalPanel ticker={futu} />
      {hk && <ShortSellingPanel ticker={futu} mode="overview" />}
      <details className="glass-card rounded-lg overflow-hidden group">
        <summary className="px-3 py-2.5 border-b border-border/30 flex items-center gap-2 cursor-pointer list-none">
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-90" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">基础信息</span>
          <ChevronDown className="h-3 w-3 ml-auto text-muted-foreground/50" />
        </summary>
        <div className="p-2">
          <StockBasicInfoPanel market={marketOfString(futu)} secType="STOCK" />
        </div>
      </details>
    </div>
  )
}

function marketOfString(futu: string): string {
  return futu.includes('.') ? futu.split('.')[0] : 'HK'
}
