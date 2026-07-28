import { useCallback, useState } from 'react'

// ─── Hook: 命令面板状态管理 ─────────────────────────────────────────
// 独立成文件，避免与 CommandPalette 组件同文件导出导致的 fast-refresh 警告。
export function useCommandPalette() {
  const [open, setOpen] = useState(false)

  const toggle = useCallback(() => setOpen((prev) => !prev), [])
  const close = useCallback(() => setOpen(false), [])

  return { open, setOpen, toggle, close }
}
