/**
 * PROD-04: 四场景模式系统（对齐 docs/01 §9.6）
 *
 * 场景模式与交易模式（SANDBOX/PAPER/LIVE）正交：
 * - 交易模式 → 安全门禁 / 下单权限
 * - 场景模式 → 布局 / 信息密度 / AI 角色
 */

// 场景模式联合类型由 SCENE_MODES 数组派生（单一事实来源）。
// 新增模式只需在数组中添加一项，TypeScript 会强制 SCENE_META 补配元数据，
// 从编译期杜绝“新增模式漏配元数据”的问题（见下方运行时兜底守卫）。
export const SCENE_MODES = ['watch', 'research', 'monitor', 'ai-analysis'] as const
export type SceneMode = (typeof SCENE_MODES)[number]

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

// ── PROD-04 健壮性加固 ────────────────────────────────────────────
// 编译期已由 `SCENE_META: Record<SceneMode, SceneMeta>` 保证每个 SceneMode 成员都有元数据；
// 此处叠加运行时兜底，拦截通过类型断言 / any 绕过编译期检查（或数组与元数据不同步）的情况。
for (const m of SCENE_MODES) {
  if (!SCENE_META[m]) {
    throw new Error(`[scene-mode-types] 场景模式 "${String(m)}" 缺少 SCENE_META 元数据配置`)
  }
}
const _sceneMetaKeys = Object.keys(SCENE_META) as SceneMode[]
if (
  _sceneMetaKeys.length !== SCENE_MODES.length ||
  !_sceneMetaKeys.every((k) => (SCENE_MODES as readonly string[]).includes(k))
) {
  throw new Error('[scene-mode-types] SCENE_META 与 SCENE_MODES 成员不一致（存在漏配或孤立的元数据）')
}

export function formatSceneLabel(mode: SceneMode): string {
  const m = SCENE_META[mode]
  return `${m.emoji} ${m.label}`
}
