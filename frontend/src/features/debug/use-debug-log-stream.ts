/**
 * FE-DEBUG-01 底部 DEBUG 面板日志流 hook
 * - 节点列表：GET /logs/stream/nodes（每 5s 刷新）
 * - 日志增量：GET /logs/stream/summary?after=&nodes=<游标JSON>（每 2s 轮询）
 * - 后端统一信封 {code, data} 已被 api-client handleResponse 解包，res.data 即内容
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'

export interface LogEntry {
  id: number
  ts: string
  level: string
  name: string
  message: string
}

export interface LogNode {
  url: string
  name: string
  aliases: string[]
  online: boolean
}

export interface LogNodeStatus extends LogNode {
  status: string
  error?: string
  last_id: number
  entries: LogEntry[]
}

interface SummaryData {
  main: { last_id: number; entries: LogEntry[] }
  nodes: LogNodeStatus[]
}

const MAX_ROWS = 400
const POLL_MS = 2000

function appendEntries(list: LogEntry[] | undefined, prev: LogEntry[]): LogEntry[] {
  if (!list || list.length === 0) return prev
  const merged = prev.concat(list)
  return merged.length > MAX_ROWS ? merged.slice(merged.length - MAX_ROWS) : merged
}

export function useDebugLogStream(paused: boolean) {
  const [nodes, setNodes] = useState<LogNode[]>([])
  const [mainEntries, setMainEntries] = useState<LogEntry[]>([])
  const [nodeEntries, setNodeEntries] = useState<Record<string, LogEntry[]>>({})
  const cursors = useRef<{ main: number; nodes: Record<string, number> }>({ main: 0, nodes: {} })
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  const loadNodes = useCallback(async () => {
    try {
      const res = await apiClient.get<{ data: { nodes: LogNode[] } }>('/logs/stream/nodes')
      const list = res.data?.nodes ?? []
      setNodes((prev) => {
        if (prev.length === list.length && prev.every((n, i) => n.url === list[i]?.url)) return prev
        return list
      })
      setNodeEntries((prev) => {
        let changed = false
        const next = { ...prev }
        for (const n of list) {
          if (!(n.url in next)) {
            next[n.url] = []
            changed = true
          }
          if (!(n.url in cursors.current.nodes)) cursors.current.nodes[n.url] = 0
        }
        return changed ? next : prev
      })
    } catch {
      /* 瞬时失败静默，下一轮重试 */
    }
  }, [])

  const poll = useCallback(async () => {
    if (pausedRef.current) return
    try {
      const res = await apiClient.get<{ data: SummaryData }>('/logs/stream/summary', {
        after: cursors.current.main,
        nodes: JSON.stringify(cursors.current.nodes),
      })
      const data = res.data
      if (!data) return
      if (data.main) {
        setMainEntries((prev) => appendEntries(data.main.entries, prev))
        if (data.main.last_id > cursors.current.main) cursors.current.main = data.main.last_id
      }
      for (const node of data.nodes ?? []) {
        if (!node || node.status !== 'ok') continue
        setNodeEntries((prev) => ({
          ...prev,
          [node.url]: appendEntries(node.entries, prev[node.url] ?? []),
        }))
        if (node.last_id > (cursors.current.nodes[node.url] ?? 0)) {
          cursors.current.nodes[node.url] = node.last_id
        }
      }
    } catch {
      /* 瞬时失败静默 */
    }
  }, [])

  useEffect(() => {
    void loadNodes()
    const nodeTimer = setInterval(() => void loadNodes(), 5000)
    const pollTimer = setInterval(() => void poll(), POLL_MS)
    return () => {
      clearInterval(nodeTimer)
      clearInterval(pollTimer)
    }
  }, [loadNodes, poll])

  const clearAll = useCallback(() => {
    setMainEntries([])
    setNodeEntries({})
  }, [])

  return { nodes, mainEntries, nodeEntries, clearAll }
}
