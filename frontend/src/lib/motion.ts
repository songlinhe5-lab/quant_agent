/**
 * FE-28: 统一动效时长与缓动（对齐 docs/04 §3.5）
 */
export const MOTION = {
  /** 模块切换 / 微交互 */
  fast: 150,
  /** 默认过渡 */
  base: 200,
  /** 面板展开 / 抽屉 */
  slow: 300,
  /** 价格闪烁 */
  flash: 400,
  /** Toast 自动消失 */
  toast: 4500,
} as const

export const EASING = {
  standard: 'cubic-bezier(0.2, 0, 0, 1)',
  emphasized: 'cubic-bezier(0.2, 0, 0, 1)',
} as const

/** Tailwind 友好 class 片段 */
export const MOTION_CLASS = {
  fast: 'duration-150 ease-out',
  base: 'duration-200 ease-out',
  slow: 'duration-300 ease-out',
} as const
