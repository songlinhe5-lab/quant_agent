'use client'

import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BarChart3, ScanSearch, Bot, Bell, MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { useSceneModeStore } from '@/stores/useSceneModeStore'
import { SCENE_MODES, SCENE_META } from '@/features/scene/scene-mode-types'

const TABS = [
  { url: '/quotes', label: '行情', icon: BarChart3 },
  { url: '/screener', label: '选股', icon: ScanSearch },
  { url: '/oms', label: 'OMS', icon: Bot },
  { url: '/alerts', label: '告警', icon: Bell },
] as const

/**
 * FE-15: <768px 底部 Tab Bar，替代左侧 Sidebar
 * PROD-04g: 补充场景模式圆盘 + 底部切换菜单
 */
export function MobileTabBar() {
  const location = useLocation()
  const openSettings = useLayoutStore((s) => s.openSettings)
  const pathname = location.pathname
  const mode = useSceneModeStore((s) => s.mode)
  const setMode = useSceneModeStore((s) => s.setMode)
  const [modeOpen, setModeOpen] = useState(false)
  const sceneMeta = SCENE_META[mode]

  return (
    <>
      {/* PROD-04g: 场景模式底部切换菜单 */}
      {modeOpen && (
        <div
          className="md:hidden fixed inset-0 z-30"
          onClick={() => setModeOpen(false)}
          aria-hidden="true"
        >
          <div
            className="absolute bottom-[calc(3.5rem+env(safe-area-inset-bottom))] inset-x-0 px-3 pb-2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="glass-card rounded-2xl border border-border/40 p-2 shadow-xl scene-accent-transition">
              <div className="px-3 py-1.5 text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                切换场景模式
              </div>
              <div className="grid grid-cols-2 gap-2">
                {SCENE_MODES.map((m) => {
                  const meta = SCENE_META[m]
                  const active = m === mode
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => {
                        setMode(m)
                        setModeOpen(false)
                      }}
                      className={cn(
                        'flex items-center gap-2 rounded-xl px-3 py-2.5 text-left transition-colors',
                        active ? 'bg-secondary/60' : 'hover:bg-secondary/30',
                      )}
                      aria-pressed={active}
                    >
                      <span className="text-lg leading-none">{meta.emoji}</span>
                      <span className="flex min-w-0 flex-col">
                        <span className={cn('text-xs font-semibold', meta.chipClass)}>{meta.label}</span>
                        <span className="truncate text-[9px] leading-tight text-muted-foreground">
                          {meta.hint}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border/40 bg-background/95 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
        aria-label="移动端主导航"
        data-testid="mobile-tab-bar"
      >
        <ul className="grid grid-cols-6 h-14">
          {TABS.map((tab) => {
            const active = pathname.startsWith(tab.url)
            return (
              <li key={tab.url}>
                <Link
                  to={tab.url}
                  className={cn(
                    'flex h-full flex-col items-center justify-center gap-0.5 text-[10px] transition-colors duration-base',
                    active ? 'text-primary' : 'text-muted-foreground',
                  )}
                  aria-current={active ? 'page' : undefined}
                >
                  <tab.icon className="h-4 w-4" aria-hidden="true" />
                  {tab.label}
                </Link>
              </li>
            )
          })}
          {/* PROD-04g: 场景模式圆盘 */}
          <li>
            <button
              type="button"
              onClick={() => setModeOpen((v) => !v)}
              className={cn(
                'flex h-full w-full flex-col items-center justify-center gap-0.5 text-[10px] transition-colors duration-base',
                modeOpen ? 'text-primary' : 'text-muted-foreground',
              )}
              aria-label="切换场景模式"
              aria-expanded={modeOpen}
            >
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border-2 text-sm leading-none scene-accent-transition',
                  sceneMeta.chipClass,
                  modeOpen && 'ring-2 ring-primary/40',
                )}
              >
                {sceneMeta.emoji}
              </span>
              模式
            </button>
          </li>
          <li>
            <button
              type="button"
              className="flex h-full w-full flex-col items-center justify-center gap-0.5 text-[10px] text-muted-foreground transition-colors duration-base"
              onClick={openSettings}
              aria-label="更多设置"
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
              更多
            </button>
          </li>
        </ul>
      </nav>
    </>
  )
}
