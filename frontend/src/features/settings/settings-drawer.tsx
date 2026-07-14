'use client'

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { useLayoutStore } from '@/stores/useLayoutStore'
import { SettingsContent } from './settings-content'

/** FE-PROD-01：右侧 Settings 抽屉，与 AI 副驾互斥 */
export function GlobalSettingsDrawer() {
  const settingsOpen = useLayoutStore((s) => s.settingsOpen)
  const closeSettings = useLayoutStore((s) => s.closeSettings)

  return (
    <Sheet
      open={settingsOpen}
      onOpenChange={(open) => {
        if (!open) closeSettings()
      }}
    >
      <SheetContent
        side="right"
        data-testid="global-settings-drawer"
        className="w-full sm:max-w-md p-0 flex flex-col gap-0 overflow-hidden"
      >
        <SheetHeader className="px-4 py-3 border-b border-border/40 shrink-0 text-left">
          <SheetTitle className="text-sm tracking-widest uppercase">Settings</SheetTitle>
          <SheetDescription className="text-xs">
            与 AI 副驾互斥；推送/三模式等见 FE-PROD-02
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <SettingsContent compact />
        </div>
      </SheetContent>
    </Sheet>
  )
}
