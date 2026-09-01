'use client'

/**
 * FIN-07 / FIN-08c · 申报归档时间轴（docs/28 §七）：跳原文 + RAG 索引状态 + 「送 RAG」。
 * 送 RAG 调 POST /financials/filings/{entity}/{accession}/ingest（FIN-08b），
 * 成功后本地回写状态；失败如实展示，不静默。
 */

import { useState } from 'react'
import { ExternalLink, FileText, Loader2, Send } from 'lucide-react'

import { EmptyState } from '@/components/ui/data-display/EmptyState'
import { DataSourceBadge } from '@/components/ui/data-display/DataSourceBadge'
import { apiClient } from '@/lib/api-client'
import logger from '@/lib/logger'
import { cn } from '@/lib/utils'
import { FINANCIALS_PATHS, type FilingItem, type IngestResult } from './api'
import { useFinancialsData } from './use-financials-data'

interface FilingsResponse {
  items: FilingItem[]
  count: number
}

// 成功写入的 chunk 数（key = accession_no）；失败记 'error'
type IngestState = Record<string, IngestResult | 'error' | 'pending'>

export function FilingTimeline({ entity }: { entity: string }) {
  const { data, loading, error } = useFinancialsData<FilingsResponse>(FINANCIALS_PATHS.filings(entity))
  const [ingestState, setIngestState] = useState<IngestState>({})

  const sendToRag = async (f: FilingItem) => {
    setIngestState((s) => ({ ...s, [f.accession_no]: 'pending' }))
    try {
      const res = await apiClient.post<{ data: IngestResult }>(
        FINANCIALS_PATHS.ingestFiling(entity, f.accession_no),
      )
      setIngestState((s) => ({ ...s, [f.accession_no]: res.data }))
    } catch (e) {
      logger.warn('送 RAG 失败', { accession: f.accession_no, error: String((e as Error)?.message || e) })
      setIngestState((s) => ({ ...s, [f.accession_no]: 'error' }))
    }
  }

  if (error) return <EmptyState title="申报列表加载失败" description={error} />
  if (!data || data.items.length === 0)
    return <EmptyState title={loading ? '加载中…' : '无申报记录'} description="请先回填该实体的申报索引" />

  return (
    <div className="space-y-2" data-testid="filing-timeline">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">共 {data.count} 份申报</span>
        <DataSourceBadge source="sec-edgar" />
      </div>
      <ol className="relative space-y-3 border-l border-gray-800 pl-4">
        {data.items.map((f) => {
          const state = ingestState[f.accession_no]
          const indexed = f.rag_indexed || (state && state !== 'error' && state !== 'pending')
          const showSend = f.doc_url && !indexed
          return (
            <li key={f.accession_no} className="relative">
              <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-violet-400" />
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <FileText className="size-4 text-gray-500" />
                <span className="font-medium text-gray-200">{f.form_type}</span>
                {f.fiscal_year !== null && <span className="text-xs text-gray-500">FY{f.fiscal_year}</span>}
                <span className="text-xs text-gray-500">{f.filed_at?.slice(0, 10) ?? '--'}</span>
                <span
                  className={cn(
                    'rounded px-1 text-[10px] leading-4',
                    indexed ? 'bg-emerald-500/15 text-emerald-400' : 'bg-gray-800 text-gray-500',
                  )}
                >
                  RAG {indexed ? '已索引' : '未索引'}
                </span>
                {state === 'pending' && <Loader2 className="size-3 animate-spin text-gray-500" />}
                {state === 'error' && <span className="text-[10px] text-red-400">入库失败，稍后重试</span>}
                {typeof state === 'object' && state !== null && (
                  <span className="text-[10px] text-emerald-400">+{state.chunks_written} 片段</span>
                )}
                {showSend && (
                  <button
                    type="button"
                    onClick={() => void sendToRag(f)}
                    disabled={state === 'pending'}
                    data-testid={`send-rag-${f.accession_no}`}
                    className="inline-flex items-center gap-1 text-xs text-violet-300 hover:text-violet-200 disabled:opacity-50"
                  >
                    送 RAG <Send className="size-3" />
                  </button>
                )}
                {f.doc_url && (
                  <a
                    href={f.doc_url}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto inline-flex items-center gap-1 text-xs text-violet-300 hover:text-violet-200"
                  >
                    原文 <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
              <p className="text-[11px] text-gray-600">{f.accession_no}</p>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export default FilingTimeline
