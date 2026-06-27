'use client'

import React from 'react'
import { ScreenerProvider, useScreenerContext } from '@/features/screener/screener-context'
import { ScreenerHeader } from '@/features/screener/screener-header'
import { ScreenerQueryPanel } from '@/features/screener/screener-query-panel'
import { ScreenerResultsTable } from '@/features/screener/screener-results-table'
import { SubscriptionManagerPanel, RagDictionaryPanel, ChartPreviewModal } from '@/features/screener/modals'
import { ScreenerAISummary } from '@/features/screener/screener-ai-summary'

function ScreenerApp() {
  const { showSubManager, showRagDict, previewData, setShowSubManager, setShowRagDict, setPreviewData, results } = useScreenerContext()

  return (
      <div className="space-y-4">
        {showSubManager && <SubscriptionManagerPanel onClose={() => setShowSubManager(false)} />}
        {showRagDict && <RagDictionaryPanel onClose={() => setShowRagDict(false)} />}
        {previewData && <ChartPreviewModal symbol={previewData.symbol} price={previewData.price} change={previewData.change} onClose={() => setPreviewData(null)} />}
        
        <ScreenerHeader />
        <ScreenerQueryPanel />
        <ScreenerAISummary results={results || []} />
        <ScreenerResultsTable />
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
