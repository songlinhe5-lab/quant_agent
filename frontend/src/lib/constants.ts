/**
 * 常量定义
 * 全局使用的常量配置
 */

// API 相关
const API_VERSION = import.meta.env.VITE_API_URL_VERSION || 'v1';
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `/api/${API_VERSION}`;
export const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

// 行情相关
export const DEFAULT_SYMBOL = 'SPY';
export const SUPPORTED_INTERVALS = ['1m', '5m', '15m', '1h', '1d', '1w'];
export const MARKET_COLORS = {
  bull: '#10b981', // emerald-500
  bear: '#ef4444', // red-500
  neutral: '#64748b', // slate-500
};

/**
 * 语义色 SSOT（JS/逻辑层用，与 globals.css 的 --bull/--bear/--warn/--info/--ai 对齐）。
 * ECharts 配置 / 图表逻辑请引用此对象，禁止在业务文件散落重复 HEX。
 */
export const SEMANTIC_COLORS = {
  bull: MARKET_COLORS.bull,
  bear: MARKET_COLORS.bear,
  warn: '#f59e0b', // amber-500
  info: '#3b82f6', // blue-500
  ai: '#8b5cf6', // violet-500
  primary: '#8b5cf6',
  accent: '#3b82f6',
  neutral: MARKET_COLORS.neutral,
} as const;

/**
 * 风险色阶 SSOT（JS/逻辑层用）。
 * - histogram: 收益分布直方图 8 阶（暗/亮双模式），与 backtest-report-stats 原值一致
 * - score：风险评分单色（高→低 红→橙→蓝→绿）
 * - 禁止在业务文件散落重复 HEX，统一引用本对象。
 */
export const RISK_COLORS = {
  /** 收益直方图 8 阶：[暗色, 亮色] */
  histogram: [
    { range: '< -5%', dark: '#f87171', light: '#dc2626' },
    { range: '-5~-3%', dark: '#fca5a5', light: '#ef4444' },
    { range: '-3~-1%', dark: '#fcd34d', light: '#f59e0b' },
    { range: '-1~0%', dark: '#d1d5db', light: '#9ca3af' },
    { range: '0~1%', dark: '#6ee7b7', light: '#10b981' },
    { range: '1~3%', dark: '#34d399', light: '#059669' },
    { range: '3~5%', dark: '#10b981', light: '#047857' },
    { range: '> 5%', dark: '#059669', light: '#064e3b' },
  ],
  /** 风险评分单色（score >= 阈值 映射）
   *  分级文案统一 SSOT: RISK_LEVEL_META (features/trading/risk-types.ts)
   *  高 >=70 / 中高 >=50 / 中等 >=30 / 低 <30 */
  score: {
    high: '#ef4444',
    medium: '#f59e0b',
    low: '#3b82f6',
    minimal: '#10b981',
  },
} as const;

// 模块列表
export const MODULES = [
  { id: 'quotes', name: '行情', icon: 'trending-up' },
  { id: 'screener', name: '选股', icon: 'search' },
  { id: 'strategy', name: '策略', icon: 'code' },
  { id: 'backtest', name: '回测', icon: 'bar-chart' },
  { id: 'oms', name: '订单', icon: 'clipboard-list' },
  { id: 'risk', name: '风控', icon: 'shield' },
  { id: 'copilot', name: 'AI', icon: 'brain' },
  { id: 'data-center', name: '数据', icon: 'database' },
  { id: 'settings', name: '设置', icon: 'settings' },
  { id: 'apm', name: '监控', icon: 'activity' },
];

// 键盘快捷键
export const SHORTCUTS = {
  'cmd+k': '打开命令面板',
  'cmd+shift+a': '切换 AI 侧边栏',
  'cmd+1': '切换到行情模块',
  'cmd+2': '切换到选股模块',
  'cmd+3': '切换到策略模块',
  escape: '关闭所有弹窗',
};

// 本地存储键
export const STORAGE_KEYS = {
  theme: 'quant-theme',
  sidebarCollapsed: 'sidebar-collapsed',
  watchlist: 'watchlist',
  activeModule: 'active-module',
  aiNarrator: 'quant-agent-ai-narrator',
  pattern: 'quant-agent-pattern',
  aiPush: 'quant-agent-ai-push',
};

// ─── AI-01 异动解说员 ───────────────────────────────────────
export const AI_NARRATOR_THRESHOLDS = [1, 2, 5] as const
export type AiNarratorThreshold = (typeof AI_NARRATOR_THRESHOLDS)[number]
export const AI_NARRATOR_DEFAULT_THRESHOLD: AiNarratorThreshold = 2

// 其他配置
export const DEBOUNCE_DELAY = 300;
export const WS_RECONNECT_INTERVAL = 5000;
export const MAX_RECONNECT_ATTEMPTS = 5;
