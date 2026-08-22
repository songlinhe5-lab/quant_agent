import type { NavigateFunction } from 'react-router-dom'

/**
 * 全局路由导航桥。
 *
 * UI 拆分后，AI Copilot 已迁至左侧「投研 / 投研会」分栏，
 * 旧的全局右侧抽屉被隐藏。`openCopilot` 等语义改为「跳转 /research」。
 *
 * 由于 react-router 的 `useNavigate` 只能在组件内使用，而部分入口位于
 * zustand store / context（非组件），这里提供可在任意位置调用的 `navigate`：
 * 由 <NavigationBridge>（挂在 DashboardLayout 内）注入真实实现。
 */
let navigateImpl: NavigateFunction | null = null

export function registerNavigate(fn: NavigateFunction) {
  navigateImpl = fn
}

export function navigate(to: string) {
  if (navigateImpl) {
    navigateImpl(to)
  } else {
    // 兜底：bridge 尚未注入（如 SSR / 首帧），用原生 history 降级
    window.history.pushState({}, '', to)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }
}
