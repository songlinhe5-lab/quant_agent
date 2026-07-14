'use client'

import { Link, useLocation } from 'react-router-dom'
import { BarChart3, ScanSearch, Bot, Bell, MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLayoutStore } from '@/stores/useLayoutStore'

const TABS = [
  { url: '/quotes', label: '行情', icon: BarChart3 },
  { url: '/screener', label: '选股', icon: ScanSearch },
  { url: '/oms', label: 'OMS', icon: Bot },
  { url: '/alerts', label: '告警', icon: Bell },
] as const

/**
 * FE-15: <768px 底部 Tab Bar，替代左侧 Sidebar
 */
export function MobileTabBar() {
  const location = useLocation()
  const openSettings = useLayoutStore((s) => s.openSettings)
  const pathname = location.pathname

  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border/40 bg-background/95 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
      aria-label="移动端主导航"
      data-testid="mobile-tab-bar"
    >
      <ul className="grid grid-cols-5 h-14">
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
  )
}
