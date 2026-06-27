/**
 * 常量定义
 * 全局使用的常量配置
 */

// API 相关
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';
export const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

// 行情相关
export const DEFAULT_SYMBOL = 'SPY';
export const SUPPORTED_INTERVALS = ['1m', '5m', '15m', '1h', '1d', '1w'];
export const MARKET_COLORS = {
  bull: '#10b981', // emerald-500
  bear: '#ef4444', // red-500
  neutral: '#64748b', // slate-500
};

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
};

// 其他配置
export const DEBOUNCE_DELAY = 300;
export const WS_RECONNECT_INTERVAL = 5000;
export const MAX_RECONNECT_ATTEMPTS = 5;
