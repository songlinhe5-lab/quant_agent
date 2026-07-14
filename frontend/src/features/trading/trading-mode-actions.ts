import { apiClient } from '@/lib/api-client'
import { confirmDanger } from '@/components/confirm-dialog'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import {
  type TradingMode,
  TRADING_MODES,
  formatModeLabel,
  getPaperCheckpointPlaceholder,
} from './trading-mode-types'

function isTradingMode(v: unknown): v is TradingMode {
  return typeof v === 'string' && (TRADING_MODES as string[]).includes(v)
}

/** 从后端拉取并写入全局 store */
export async function hydrateTradingMode(): Promise<TradingMode> {
  const store = useTradingModeStore.getState()
  try {
    const res = await apiClient.get('/oms/mode')
    const mode = res.data?.data?.mode
    if (isTradingMode(mode)) {
      store.setMode(mode)
      store.setHydrated(true)
      return mode
    }
  } catch {
    /* 保持默认 SANDBOX */
  }
  store.setHydrated(true)
  return store.mode
}

function buildSwitchDescription(from: TradingMode, to: TradingMode): string {
  if (to === 'LIVE' && from === 'PAPER') {
    const cp = getPaperCheckpointPlaceholder()
    return [
      `即将进入实盘模式，所有交易将使用真实资金。`,
      ``,
      `纸面检查点摘要（${cp.portfolioName}）:`,
      `· 运行天数: ${cp.runDays}`,
      `· Sharpe: ${cp.sharpe}`,
      `· TE: ${cp.trackingError}`,
      `· ${cp.note}`,
    ].join('\n')
  }
  if (to === 'LIVE' && from === 'SANDBOX') {
    return [
      '禁止从 SANDBOX 直接跳 LIVE（产品规则 §1.6）。',
      '建议路径：SANDBOX → PAPER（长期验证）→ LIVE。',
      '',
      '若坚持显式风险确认，请在下方输入 LIVE 继续。',
    ].join('\n')
  }
  if (to === 'PAPER') {
    return '切换到 PAPER：常驻纸面组合，虚拟账本记账，不影响真实资金。'
  }
  if (to === 'SANDBOX') {
    return '切换到 SANDBOX：单次推演沙箱，无持久账本。'
  }
  if (to === 'LIVE') {
    return '即将进入实盘模式，所有交易将使用真实资金。请确认已充分了解风险。'
  }
  return `确认切换: ${formatModeLabel(from)} → ${formatModeLabel(to)}`
}

/**
 * 带二次确认的模式切换。成功后更新 store；失败返回 false。
 * @returns 是否已切换成功
 */
export async function requestTradingModeSwitch(target: TradingMode): Promise<boolean> {
  const store = useTradingModeStore.getState()
  const current = store.mode
  if (target === current) return true

  const opts =
    target === 'LIVE' && current === 'SANDBOX'
      ? { confirmLabel: '确认进入 LIVE', cancelLabel: '取消', requireInputConfirm: 'LIVE' }
      : target === 'LIVE'
        ? { confirmLabel: '确认进入 LIVE', cancelLabel: '取消', requireInputConfirm: 'LIVE' }
        : { confirmLabel: '确认切换', cancelLabel: '取消' }

  const confirmed = await confirmDanger(
    `切换交易模式: ${current} → ${target}`,
    buildSwitchDescription(current, target),
    opts,
  )
  if (!confirmed) return false

  try {
    const res = await apiClient.post('/oms/mode/switch', { mode: target })
    if (res.data?.status === 'success') {
      store.setMode(target)
      return true
    }
  } catch {
    /* toast 由调用方处理 */
  }
  return false
}

export function applyTradingModeFromWs(mode: unknown) {
  if (isTradingMode(mode)) {
    useTradingModeStore.getState().setMode(mode)
  }
}
