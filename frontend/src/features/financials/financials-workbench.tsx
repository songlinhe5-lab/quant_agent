'use client'

/**
 * FIN-07 · 个股财报工作台（docs/28 §七）
 * 布局 SSOT：由 App.tsx 挂在 DashboardLayout 下；本页只做实体选择 + 七组件 tab。
 */

import { Suspense, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { InitOverlay } from '@/components/ui/data-display/InitOverlay'
import { cn } from '@/lib/utils'
import { DupontPanel } from './dupont-panel'
import { FilingTimeline } from './filing-timeline'
import { MdaDiffPanel } from './mda-diff-panel'
import { PeerCompare } from './peer-compare'
import { QualityScorecard } from './quality-scorecard'
import { RestatementDiff } from './restatement-diff'
import { StatementGrid } from './statement-grid'
import { TrendChart } from './trend-chart'

const TABS = [
  { id: 'statements', label: '多期报表', node: (e: string) => <StatementGrid entity={e} /> },
  { id: 'trend', label: '趋势', node: (e: string) => <TrendChart entity={e} /> },
  { id: 'dupont', label: 'DuPont', node: (e: string) => <DupontPanel entity={e} /> },
  { id: 'peers', label: '同业', node: (e: string) => <PeerCompare entity={e} /> },
  { id: 'quality', label: '质量记分卡', node: (e: string) => <QualityScorecard entity={e} /> },
  { id: 'timeline', label: '申报时间轴', node: (e: string) => <FilingTimeline entity={e} /> },
  { id: 'restatements', label: '重述 diff', node: (e: string) => <RestatementDiff entity={e} /> },
  { id: 'mdadiff', label: 'MD&A diff', node: (e: string) => <MdaDiffPanel entity={e} /> },
] as const

type TabId = (typeof TABS)[number]['id']

export function FinancialsWorkbench() {
  const [params, setParams] = useSearchParams()
  // entity 持久到 URL，方便从选股/行情页带 symbol 跳进来
  const entity = (params.get('entity') ?? '').trim().toUpperCase()
  const [draft, setDraft] = useState(entity)
  const tab = (params.get('tab') as TabId) ?? 'statements'
  const activeTab = TABS.find((t) => t.id === tab) ?? TABS[0]

  const apply = (value: string) => {
    const next = value.trim().toUpperCase()
    setDraft(next)
    if (next) setParams({ entity: next, tab: activeTab.id })
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold text-gray-100">财报看板</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            apply(draft)
          }}
          className="flex items-center gap-2"
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="实体：AAPL / US:CIK0000320193 / 00700 / 600519"
            className="w-72 rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200"
            data-testid="entity-input"
          />
          <button
            type="submit"
            className="rounded border border-violet-500/40 bg-violet-500/10 px-3 py-1.5 text-sm text-violet-300"
          >
            加载
          </button>
        </form>
      </div>

      {!entity ? (
        <InitOverlay label="输入实体以加载财报（支持美股 ticker / CIK、港股、A 股代码）" variant="skeleton" />
      ) : (
        <>
          <nav className="flex flex-wrap gap-1 border-b border-gray-800 pb-2">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setParams({ entity, tab: t.id })}
                data-testid={`tab-${t.id}`}
                className={cn(
                  'rounded px-3 py-1.5 text-sm',
                  t.id === activeTab.id
                    ? 'bg-violet-500/15 text-violet-300'
                    : 'text-gray-400 hover:text-gray-200',
                )}
              >
                {t.label}
              </button>
            ))}
            <span className="ml-auto self-center text-xs text-gray-500">{entity}</span>
          </nav>
          <Suspense fallback={<InitOverlay label="组件加载中…" />}>{activeTab.node(entity)}</Suspense>
        </>
      )}
    </div>
  )
}

export default FinancialsWorkbench
