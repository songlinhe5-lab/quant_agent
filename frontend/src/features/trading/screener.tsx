'use client'

import React, { useState } from 'react'
import { ScreenerProvider, useScreenerContext } from '@/features/screener/screener-context'
import { ScreenerHeader } from '@/features/screener/screener-header'
import { ScreenerQueryPanel } from '@/features/screener/screener-query-panel'
import { ScreenerResultsTable } from '@/features/screener/screener-results-table'
import { SubscriptionManagerPanel, RagDictionaryPanel, ChartPreviewModal } from '@/features/screener/modals'
import { ScreenerAISummary } from '@/features/screener/screener-ai-summary'
import { CEPPanel } from '@/features/screener/cep-panel'
import { PortfolioBacktestDialog } from '@/features/screener/portfolio-backtest-dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

function ScreenerApp() {
  const { showSubManager, showRagDict, previewData, setShowSubManager, setShowRagDict, setPreviewData, results, selected } = useScreenerContext()
  const [showBacktest, setShowBacktest] = useState(false)

  return (
      <div className="space-y-4">
        {showSubManager && <SubscriptionManagerPanel onClose={() => setShowSubManager(false)} />}
        {showRagDict && <RagDictionaryPanel onClose={() => setShowRagDict(false)} />}
        {previewData && <ChartPreviewModal symbol={previewData.symbol} price={previewData.price} change={previewData.change} onClose={() => setPreviewData(null)} />}
        {showBacktest && selected.length > 0 && <PortfolioBacktestDialog symbols={selected} onClose={() => setShowBacktest(false)} />}
        
        <ScreenerHeader />
        <ScreenerQueryPanel />

        <Tabs defaultValue="results" className="w-full">
          <TabsList className="h-8">
            <TabsTrigger value="results" className="text-xs">筛选结果</TabsTrigger>
            <TabsTrigger value="cep" className="text-xs">CEP 异动</TabsTrigger>
          </TabsList>
          <TabsContent value="results" className="mt-2 space-y-2">
            {selected.length >= 2 && (
              <div className="flex justify-end">
                <button onClick={() => setShowBacktest(true)} className="text-xs px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 transition-colors font-medium">
                  一键组合回测 ({selected.length} 只)
                </button>
              </div>
            )}
            <ScreenerAISummary results={results || []} />
            <ScreenerResultsTable />
          </TabsContent>
          <TabsContent value="cep" className="mt-2">
            <CEPPanel />
          </TabsContent>
        </Tabs>
      </div>
    )
}

export function ScreenerModule() {
  return (
    <ScreenerProvider>
      <ScreenerApp />
    </ScreenerProvider>
  )
}
