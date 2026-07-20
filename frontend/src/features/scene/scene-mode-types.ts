/**
 * PROD-04: 四场景模式系统（对齐 docs/01 §9.6）
 *
 * 场景模式与交易模式（SANDBOX/PAPER/LIVE）正交：
 * - 交易模式 → 安全门禁 / 下单权限
 * - 场景模式 → 布局 / 信息密度 / AI 角色
 */

export type SceneMode = 'watch' | 'research' | 'monitor' | 'ai-analysis'

export const SCENE_MODES: SceneMode[] = ['watch', 'research', 'monitor', 'ai-analysis']

export type AiRole = 'hidden' | 'drawer' | 'entry' | 'fullscreen'

export interface SceneMeta {
  /** 中文标签 */
  label: string
  /** 短标签（切换器按钮） */
  short: string
  /** 模式标识 emoji */
  emoji: string
  /** CSS --density-scale 值 */
  density: number
  /** CSS --scene-accent HSL 值 (H S% L%) */
  accentHsl: string
  /** 切换器激活态 Tailwind class */
  chipClass: string
  /** AI Copilot 在此模式下的角色 */
  aiRole: AiRole
  /** 侧边栏是否可见 */
  sidebarVisible: boolean
  /** 悬浮提示 */
  hint: string
}

export const SCENE_META: Record<SceneMode, SceneMeta> = {
  watch: {
    label: '盯盘模式',
    short: '盯盘',
    emoji: '🟢',
    density: 1.2,
    accentHsl: '160 84% 45%',
    chipClass: 'text-emerald-500',
    aiRole: 'hidden',
    sidebarVisible: false,
    hint: 'K线全屏 · 大字体 · 高对比 · AI 隐藏（右键唤起）',
  },
  research: {
    label: '研究模式',
    short: '研究',
    emoji: '🟣',
    density: 0.9,
    accentHsl: '270 70% 60%',
    chipClass: 'text-violet-500',
    aiRole: 'drawer',
    sidebarVisible: true,
    hint: '多面板并排 · AI 编码助手常驻 · 极密密度',
  },
  monitor: {
    label: '监控模式',
    short: '监控',
    emoji: '🟠',
    density: 1.0,
    accentHsl: '38 92% 50%',
    chipClass: 'text-amber-500',
    aiRole: 'entry',
    sidebarVisible: true,
    hint: '告警流 · Bot 状态矩阵 · 风控仪表 · AI 告警分析',
  },
  'ai-analysis': {
    label: 'AI 分析',
    short: 'AI',
    emoji: '🔵',
    density: 1.0,
    accentHsl: '217 91% 60%',
    chipClass: 'text-blue-500',
    aiRole: 'fullscreen',
    sidebarVisible: false,
    hint: '全宽对话流 · 内联图表/数据卡片 · 操作按钮闭环',
  },
}

export function formatSceneLabel(mode: SceneMode): string {
  const m = SCENE_META[mode]
  return `${m.emoji} ${m.label}`
}
