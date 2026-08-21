/**
 * COPILOT-10: 快捷指令单一配置源。
 * 合并三套并存指令为统一模块，消除 chat-context / fullscreen-copilot / chat.py 三处分散定义。
 *
 * 三类指令：
 *  - pageCommands:     页面级预填式（抽屉欢迎页，含 {输入标的} 占位符）
 *  - sceneCommands:    场景级（全屏投研工作台，可选自动携带当前 ticker）
 *  - dynamicFallback:  动态建议兜底（后端 /chat/suggestions 失败时的静态回退）
 */

// ─── 页面级：个股深度研判快捷指令（抽屉欢迎页 4 宫格） ───

export interface PageQuickCommand {
  emoji: string
  label: string
  template: string
}

export const PAGE_QUICK_COMMANDS: PageQuickCommand[] = [
  { emoji: '📊', label: '个股深度研判', template: '请对 {输入标的} 进行深度研判，综合基本面、技术面和估值，给出投资建议。' },
  { emoji: '🔄', label: '对标分析', template: '请将 {输入标的} 与行业内 top 3 竞品进行对标分析。' },
  { emoji: '⚠️', label: '财务异常检测', template: '请检测 {输入标的} 是否存在财务异常信号。' },
  { emoji: '🎯', label: '目标价评估', template: '请评估 {输入标的} 12个月目标价空间，给出悲观/中性/乐观三档估值。' },
]

// ─── 场景级：AI 分析工作台快捷指令栏 ───

export interface SceneQuickCommand {
  key: string
  emoji: string
  label: string
  /** 是否需要内联当前聚焦标的 ticker */
  ticker: boolean
  template: string
}

export const SCENE_QUICK_COMMANDS: SceneQuickCommand[] = [
  {
    key: 'morning',
    emoji: '🌤️',
    label: '今日早报',
    ticker: false,
    template: '请生成今日盘前推演早报，调用宏观新闻与行情工具，汇总全球宏观高危事件、核心标的监控与多空研判，并生成内联数据卡片。',
  },
  {
    key: 'compare',
    emoji: '⚖️',
    label: '对比分析',
    ticker: true,
    template: '请对比分析 {symbol} 与同行业 top 3 竞品，调用行情与基本面工具，从估值、技术面与资金面给出差异化研判，并生成内联对比图表。',
  },
  {
    key: 'option',
    emoji: '📡',
    label: '期权链',
    ticker: true,
    template: '请拉取 {symbol} 的期权链 (OPTION_CHAIN)，分析隐含波动率曲面与多空持仓结构，给出期权策略建议，并生成内联图表。',
  },
  {
    key: 'macro',
    emoji: '🌐',
    label: '宏观雷达',
    ticker: false,
    template: '请扫描当前全球宏观高危事件与情绪雷达（VIX、P/C Ratio、利率、FRED 数据），调用宏观工具给出风险推演，并生成内联图表。',
  },
  {
    key: 'watchlist',
    emoji: '📋',
    label: '查询自选',
    ticker: false,
    template: '请列出我的自选股池，调用行情工具做整体强弱扫描、异动提示与板块分布，并生成内联数据卡片。',
  },
]

// ─── 动态建议兜底（后端 /chat/suggestions 失败时的静态回退） ───

export interface DynamicSuggestion {
  title: string
  prompt: string
}

export const DYNAMIC_SUGGESTION_FALLBACK: DynamicSuggestion[] = [
  { title: '今日宏观风向', prompt: '提取今天全球核心经济体的宏观大事件，并给出你的风险判断。' },
  { title: '个股研报分析', prompt: '分析 0700.HK (腾讯控股) 最近的动态，结合基本面给出一份研报。' },
  { title: '生成交易策略', prompt: '请帮我用 Python 写一个双均线 (MA10, MA20) 交叉的实盘策略框架。' },
  { title: '技术面诊股', prompt: '帮我分析下 AAPL (苹果) 的最新走势。' },
]

// ─── 向后兼容重导出（避免下游批量改 import 路径） ───

/** @deprecated 使用 PAGE_QUICK_COMMANDS */
export const STOCK_QUICK_COMMANDS = PAGE_QUICK_COMMANDS
export type StockQuickCommand = PageQuickCommand
