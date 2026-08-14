'use client'

import { useNavigate } from 'react-router-dom'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { SCENE_MODES, SCENE_META, type SceneMode } from '@/features/scene/scene-mode-types'
import { cn } from '@/lib/utils'

/**
 * PROD-04: 顶栏场景模式分段切换器
 * 对标 TradingModeSwitcher，控制布局/密度/AI角色（与 SANDBOX/PAPER/LIVE 正交）
 *
 * 2026-08-14：场景切换同时导航到对应独立页面（watch→/quotes, research→/strategy,
 * monitor→/monitor, ai-analysis→/copilot）。Quotes 模块不再被监控/研究场景劫持，
 * 监控总览 / 研究 IDE 各自独立成页，避免 Quotes 行情页被顶替。
 */
const SCENE_ROUTE: Record<SceneMode, string> = {
  watch: '/quotes',
  research: '/strategy',
  monitor: '/monitor',
  'ai-analysis': '/copilot',
}

export function SceneModeSwitcher({ className }: { className?: string }) {
  const mode = useSceneModeStore((s) => s.mode)
  const setMode = useSceneModeStore((s) => s.setMode)
  const navigate = useNavigate()

  return (
    <div
      data-testid="scene-mode-switcher"
      role="radiogroup"
      aria-label="场景模式"
      className={cn(
        'hidden sm:flex items-center rounded-lg border border-slate-200 dark:border-slate-800 p-0.5 bg-slate-100/80 dark:bg-slate-900/80',
        className,
      )}
    >
      {SCENE_MODES.map((m: SceneMode) => {
        const active = mode === m
        const meta = SCENE_META[m]
        return (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => {
              setMode(m)
              navigate(SCENE_ROUTE[m])
            }}
            className={cn(
              'px-2 py-1 rounded-md text-[10px] font-bold font-mono tracking-wide transition-colors',
              active
                ? cn('bg-background shadow-sm', meta.chipClass)
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200',
            )}
            title={meta.hint}
          >
            {meta.emoji}
            {meta.short}
          </button>
        )
      })}
    </div>
  )
}
