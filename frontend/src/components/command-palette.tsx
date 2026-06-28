/**
 * Cmd+K 命令面板 (Command Palette)
 * FE-06: 快速跳转标的、模块，键盘优先操作流
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  Search,
  BarChart3,
  Globe,
  ScanSearch,
  Code2,
  FlaskConical,
  Bot,
  ShieldAlert,
  Brain,
  Settings,
  TrendingUp,
  ArrowRight,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import logger from '@/lib/logger'

// ─── 命令项类型 ─────────────────────────────────────────────────────
interface CommandItem {
  id: string
  label: string
  description?: string
  icon?: React.ComponentType<{ className?: string }>
  keywords?: string[]
  action: () => void
  group: string
  shortcut?: string
}

// ─── Props ──────────────────────────────────────────────────────────
interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onModuleChange?: (moduleId: string) => void
  onSymbolSelect?: (symbol: string) => void
  className?: string
}

// ─── 模块定义 ───────────────────────────────────────────────────────
const MODULES: { id: string; label: string; icon: React.ComponentType<{ className?: string }>; keywords: string[] }[] = [
  { id: 'quotes', label: '行情盘口', icon: BarChart3, keywords: ['行情', '盘口', 'quotes', 'market', 'price'] },
  { id: 'data-center', label: '数据中心', icon: Globe, keywords: ['数据', '宏观', 'data', 'macro', 'center'] },
  { id: 'screener', label: '量化选股', icon: ScanSearch, keywords: ['选股', '筛选', 'screener', 'filter'] },
  { id: 'strategy', label: '策略研发', icon: Code2, keywords: ['策略', '代码', 'strategy', 'code'] },
  { id: 'backtest', label: '回测引擎', icon: FlaskConical, keywords: ['回测', '测试', 'backtest', 'test'] },
  { id: 'oms', label: '订单中枢', icon: Bot, keywords: ['订单', 'oms', 'order'] },
  { id: 'risk', label: '风控归因', icon: ShieldAlert, keywords: ['风控', '风险', 'risk'] },
  { id: 'copilot', label: 'AI 助手', icon: Brain, keywords: ['AI', '助手', 'copilot', 'chat'] },
  { id: 'settings', label: '系统设置', icon: Settings, keywords: ['设置', '配置', 'settings', 'config'] },
]

// ─── 常用标的 ───────────────────────────────────────────────────────
const POPULAR_SYMBOLS = [
  { symbol: 'HK.00700', name: '腾讯控股', keywords: ['腾讯', 'tencent', '700'] },
  { symbol: 'HK.09988', name: '阿里巴巴', keywords: ['阿里', 'alibaba', '9988'] },
  { symbol: 'US.AAPL', name: '苹果公司', keywords: ['苹果', 'apple', 'aapl'] },
  { symbol: 'US.MSFT', name: '微软公司', keywords: ['微软', 'microsoft', 'msft'] },
  { symbol: 'US.TSLA', name: '特斯拉', keywords: ['特斯拉', 'tesla', 'tsla'] },
  { symbol: 'US.NVDA', name: '英伟达', keywords: ['英伟达', 'nvidia', 'nvda'] },
  { symbol: 'US.BABA', name: '阿里巴巴(美)', keywords: ['阿里', 'alibaba', 'baba'] },
  { symbol: 'HK.09888', name: '百度集团', keywords: ['百度', 'baidu', '9888'] },
]

// ─── 主组件 ─────────────────────────────────────────────────────────
export function CommandPalette({
  open,
  onOpenChange,
  onModuleChange,
  onSymbolSelect,
  className,
}: CommandPaletteProps) {
  const [search, setSearch] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // ─── 构建命令列表 ───────────────────────────────────────────────
  const commands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = []

    // 模块跳转
    MODULES.forEach((mod) => {
      items.push({
        id: `module-${mod.id}`,
        label: mod.label,
        description: `跳转到${mod.label}模块`,
        icon: mod.icon,
        keywords: mod.keywords,
        group: '模块导航',
        action: () => {
          onModuleChange?.(mod.id)
          logger.debug('[CommandPalette] 模块跳转', { module: mod.id })
        },
      })
    })

    // 常用标的
    POPULAR_SYMBOLS.forEach((sym) => {
      items.push({
        id: `symbol-${sym.symbol}`,
        label: sym.symbol,
        description: sym.name,
        icon: TrendingUp,
        keywords: [...sym.keywords, sym.name],
        group: '常用标的',
        action: () => {
          onSymbolSelect?.(sym.symbol)
          logger.debug('[CommandPalette] 选择标的', { symbol: sym.symbol })
        },
      })
    })

    // 快捷操作
    items.push({
      id: 'action-refresh',
      label: '刷新数据',
      description: '重新拉取所有行情数据',
      keywords: ['刷新', 'refresh', 'reload'],
      icon: ArrowRight,
      group: '快捷操作',
      shortcut: '⌘R',
      action: () => {
        window.location.reload()
      },
    })

    items.push({
      id: 'action-theme',
      label: '切换主题',
      description: '在深色/浅色模式间切换',
      keywords: ['主题', 'theme', 'dark', 'light'],
      icon: ArrowRight,
      group: '快捷操作',
      action: () => {
        const root = document.documentElement
        root.classList.toggle('dark')
      },
    })

    return items
  }, [onModuleChange, onSymbolSelect])

  // ─── 过滤命令 ───────────────────────────────────────────────────
  const filteredCommands = useMemo(() => {
    if (!search.trim()) return commands

    const query = search.toLowerCase()
    return commands.filter((cmd) => {
      // 匹配 label
      if (cmd.label.toLowerCase().includes(query)) return true
      // 匹配 description
      if (cmd.description?.toLowerCase().includes(query)) return true
      // 匹配 keywords
      if (cmd.keywords?.some((kw) => kw.toLowerCase().includes(query))) return true
      return false
    })
  }, [commands, search])

  // ─── 分组命令 ───────────────────────────────────────────────────
  const groupedCommands = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {}
    filteredCommands.forEach((cmd) => {
      if (!groups[cmd.group]) groups[cmd.group] = []
      groups[cmd.group].push(cmd)
    })
    return groups
  }, [filteredCommands])

  // ─── 键盘快捷键 ─────────────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+K 或 Ctrl+K 打开
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        onOpenChange(!open)
      }
      // Esc 关闭
      if (e.key === 'Escape' && open) {
        onOpenChange(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onOpenChange])

  // ─── 执行命令 ───────────────────────────────────────────────────
  const executeCommand = useCallback((cmd: CommandItem) => {
    setIsLoading(true)
    try {
      cmd.action()
    } catch (e) {
      logger.error('[CommandPalette] 命令执行失败', e as Error)
    } finally {
      setIsLoading(false)
      onOpenChange(false)
      setSearch('')
    }
  }, [onOpenChange])

  // ─── 未打开时不渲染 ─────────────────────────────────────────────
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]" onClick={() => onOpenChange(false)}>
      {/* 背景遮罩 */}
      <div className="absolute inset-0 bg-background/80 backdrop-blur-sm" aria-hidden="true" />

      {/* 命令面板 */}
      <div
        className={cn(
          'relative w-full max-w-lg rounded-xl border border-border/50',
          'bg-popover shadow-2xl shadow-black/20',
          'overflow-hidden',
          className
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="命令面板"
      >
        {/* 搜索输入 */}
        <div className="flex items-center border-b border-border/50 px-4">
          {isLoading ? (
            <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" aria-hidden="true" />
          ) : (
            <Search className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
          <input
            ref={inputRef}
            type="text"
            placeholder="输入命令或搜索..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 h-12 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            autoFocus
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <kbd className="hidden sm:inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
            ESC
          </kbd>
        </div>

        {/* 命令列表 */}
        <div className="max-h-[300px] overflow-y-auto p-2">
          {Object.keys(groupedCommands).length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              未找到匹配的命令
            </div>
          ) : (
            Object.entries(groupedCommands).map(([group, items]) => (
              <div key={group} className="mb-2">
                <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {group}
                </div>
                {items.map((cmd) => (
                  <CommandItem
                    key={cmd.id}
                    item={cmd}
                    onSelect={() => executeCommand(cmd)}
                  />
                ))}
              </div>
            ))
          )}
        </div>

        {/* 底部提示 */}
        <div className="flex items-center justify-between border-t border-border/50 px-4 py-2 text-[10px] text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="h-4 w-4 flex items-center justify-center rounded border border-border/50 bg-muted text-[9px]">↑</kbd>
              <kbd className="h-4 w-4 flex items-center justify-center rounded border border-border/50 bg-muted text-[9px]">↓</kbd>
              导航
            </span>
            <span className="flex items-center gap-1">
              <kbd className="h-4 px-1 flex items-center justify-center rounded border border-border/50 bg-muted text-[9px]">↵</kbd>
              选择
            </span>
          </div>
          <span>QuantEdge Pro</span>
        </div>
      </div>
    </div>
  )
}

// ─── 命令项组件 ─────────────────────────────────────────────────────
interface CommandItemProps {
  item: CommandItem
  onSelect: () => void
}

function CommandItem({ item, onSelect }: CommandItemProps) {
  const Icon = item.icon

  return (
    <button
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm',
        'hover:bg-accent hover:text-accent-foreground',
        'focus:bg-accent focus:text-accent-foreground focus:outline-none',
        'transition-colors duration-100'
      )}
      onClick={onSelect}
    >
      {Icon && <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" aria-hidden="true" />}
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{item.label}</div>
        {item.description && (
          <div className="text-xs text-muted-foreground truncate">{item.description}</div>
        )}
      </div>
      {item.shortcut && (
        <kbd className="text-[10px] text-muted-foreground font-mono">{item.shortcut}</kbd>
      )}
    </button>
  )
}

// ─── Hook: 命令面板状态管理 ─────────────────────────────────────────
export function useCommandPalette() {
  const [open, setOpen] = useState(false)

  const toggle = useCallback(() => setOpen((prev) => !prev), [])
  const close = useCallback(() => setOpen(false), [])

  return { open, setOpen, toggle, close }
}

export default CommandPalette
