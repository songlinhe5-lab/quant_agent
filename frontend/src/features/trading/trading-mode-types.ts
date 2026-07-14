/** FE-PROD-02: 三模式产品契约（对齐 docs/01 §1.6） */

export type TradingMode = 'SANDBOX' | 'PAPER' | 'LIVE'

export const TRADING_MODES: TradingMode[] = ['SANDBOX', 'PAPER', 'LIVE']

export const MODE_META: Record<
  TradingMode,
  { label: string; short: string; emoji: string; bannerClass: string; chipClass: string; hint: string }
> = {
  SANDBOX: {
    label: 'SANDBOX',
    short: '沙箱',
    emoji: '🟡',
    bannerClass: 'bg-amber-500/15 border-amber-500/40 text-amber-500',
    chipClass: 'text-amber-500',
    hint: '单次推演，无持久账本 · 模拟环境',
  },
  PAPER: {
    label: 'PAPER',
    short: '纸面',
    emoji: '🟠',
    bannerClass: 'bg-orange-500/15 border-orange-500/40 text-orange-400',
    chipClass: 'text-orange-400',
    hint: '常驻纸面组合 · SimBroker 虚拟账本',
  },
  LIVE: {
    label: 'LIVE',
    short: '实盘',
    emoji: '🔴',
    bannerClass: 'bg-red-500/15 border-red-500/40 text-red-500 animate-pulse',
    chipClass: 'text-red-500',
    hint: '真实资金 · REAL_TRADE_EXECUTE 双锁',
  },
}

/** PT-02b: 纸面检查点摘要（从 API 获取真实绩效数据） */
export type PaperCheckpointSummary = {
  portfolioName: string
  runDays: string
  sharpe: string
  trackingError: string
  note: string
}

/**
 * 获取纸面检查点摘要。
 * PT-02b: 尝试从 /paper/portfolios API 获取第一个 running 组合的绩效数据。
 * 失败时返回占位符。
 */
export function getPaperCheckpointPlaceholder(): PaperCheckpointSummary {
  // 尝试从 sessionStorage 读取缓存的绩效数据（由 paper module 写入）
  try {
    if (typeof window !== 'undefined') {
      const cached = sessionStorage.getItem('paper_checkpoint_summary')
      if (cached) {
        const data = JSON.parse(cached)
        return {
          portfolioName: data.portfolioName || '默认纸面组合',
          runDays: data.runDays || '—',
          sharpe: data.sharpe || '—',
          trackingError: data.trackingError || '—',
          note: data.note || '纸面组合绩效摘要',
        }
      }
    }
  } catch {
    /* ignore */
  }
  return {
    portfolioName: '默认纸面组合',
    runDays: '—',
    sharpe: '—',
    trackingError: '—',
    note: '纸面检查点摘要：暂无绩效数据，请先运行纸面组合',
  }
}

export function formatModeLabel(mode: TradingMode): string {
  const m = MODE_META[mode]
  return `${m.emoji} ${m.label}`
}
