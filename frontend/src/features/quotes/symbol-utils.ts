/**
 * 行情页 symbol 归一化工具。
 *
 * Quotes 自选池使用「市场后缀式」（如 `00700.HK` / `BTC/USD`），
 * 而个股微观面板（data-center）与期权组件（options）要求 Futu「市场前缀式」
 * （如 `HK.00700` / `US.AAPL`）。此工具负责双向/归一转换。
 */

const MARKET_CODES = ['HK', 'US', 'CN', 'SG', 'JP', 'AU', 'UK', 'DE', 'KR', 'TW', 'IT', 'FR', 'ES', 'NL', 'BR', 'CA', 'IN']

/** 市场前缀式（Futu 规范）：`US.AAPL` / `HK.00700` */
export function toMarketSymbol(input: string): string {
  if (!input) return input
  const s = input.trim().toUpperCase()

  // BTC/USD 这类加密对，原样返回（期权/微观面板不支持，调用方应过滤）
  if (s.includes('/')) return s

  // 已含 '.' —— 判断是「市场前缀式」还是「市场后缀式」
  if (s.includes('.')) {
    const [a, b] = s.split('.')
    if (MARKET_CODES.includes(a)) {
      // 已是市场前缀式：HK.00700 / US.AAPL
      return s
    }
    if (MARKET_CODES.includes(b)) {
      // 市场后缀式：00700.HK → HK.00700
      return `${b}.${a}`
    }
    // 未知结构，原样返回
    return s
  }

  // 无市场前缀：AAPL → 默认 US
  return `US.${s}`
}

/** 市场代码：`HK.00700` / `00700.HK` → `HK` */
export function marketOf(input: string): string {
  if (!input) return ''
  const s = input.trim().toUpperCase()
  if (s.includes('.')) {
    const [a, b] = s.split('.')
    return MARKET_CODES.includes(a) ? a : MARKET_CODES.includes(b) ? b : ''
  }
  return ''
}

/** 是否港股（用于卖空拥挤度仅港股显示） */
export function isHkMarket(input: string): boolean {
  return marketOf(input) === 'HK'
}
