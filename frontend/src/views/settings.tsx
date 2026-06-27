'use client'

import { useEffect, useState } from 'react'
import { ShieldAlert, Globe, MonitorSmartphone, Activity, Palette } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import { useApi } from '@/hooks/use-api'

export default function SettingsPage() {
  const { toast } = useToast()
  const { execute, isLoading } = useApi()
  
  // 前端默认状态，将在拉取到后端配置后覆盖
  const [prefs, setPrefs] = useState({
    theme: 'dark',
    defaultLeverage: 1.0,
    yfinanceFallbackEnabled: true,
    language: 'zh-CN'
  })

  useEffect(() => {
    fetchPrefs()
  }, [])
  
  // 动态切换根节点的 Tailwind 暗黑类名
  const applyTheme = (theme: string) => {
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    let appliedTheme = theme
    if (theme === 'system') {
      appliedTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    
    root.classList.add(appliedTheme)
    localStorage.setItem('quant-theme', appliedTheme)
  }

  const fetchPrefs = async () => {
    try {
      // 请求后端，路径由 apiClient 的 baseURL 自动补全
      const res = await execute('/settings/preferences', { method: 'GET' })
      if (res.status === 'success' && res.data) {
        setPrefs(res.data)
        // 拉取到后端数据后，立即应用主题
        if (res.data.theme) applyTheme(res.data.theme)
      }
    } catch (error) {
      console.error('Failed to fetch preferences', error)
    }
  }

  const updatePref = async (key: string, value: any) => {
    // 1. 乐观 UI 更新：先在前端让开关迅速改变状态，提升交互丝滑度
    setPrefs((prev) => ({ ...prev, [key]: value }))
    
    // 如果修改的是主题，立即响应到 DOM
    if (key === 'theme') applyTheme(value)

    // 2. 将改动发送给后端持久化
    try {
      await execute('/settings/preferences', {
        method: 'POST',
        data: { [key]: value },
      })
      toast({
        title: '设置已保存',
        description: `系统全局配置已同步至数据库。`,
      })
    } catch (error) {
      // 如果后端报错，重置前端状态
      fetchPrefs() 
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">系统全局设置</h1>
        <p className="text-muted-foreground text-sm mt-1">管理量化引擎偏好、风控底线与容灾策略。</p>
      </div>

      <div className="grid gap-6">
        {/* 外观与主题 */}
        <div className="glass-card rounded-xl p-5 border border-border/40">
          <div className="flex items-center gap-2 mb-4">
            <Palette className="h-5 w-5 text-violet-400" />
            <h2 className="font-semibold text-base">外观与主题</h2>
          </div>
          <div className="flex items-center justify-between py-3 border-t border-border/30">
            <div className="space-y-1">
              <span className="text-sm font-medium">界面颜色模式</span>
              <p className="text-xs text-muted-foreground max-w-[500px]">选择适合您当前环境的终端显示主题，暗黑模式更适合沉浸式看盘。</p>
            </div>
            <Select disabled={isLoading} value={prefs.theme} onValueChange={(val: any) => updatePref('theme', val)}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="选择主题" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dark">暗黑模式 (Dark)</SelectItem>
                <SelectItem value="light">明亮模式 (Light)</SelectItem>
                <SelectItem value="system">跟随系统 (System)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* 数据源与容灾设置 */}
        <div className="glass-card rounded-xl p-5 border border-border/40">
          <div className="flex items-center gap-2 mb-4">
            <Globe className="h-5 w-5 text-sky-400" />
            <h2 className="font-semibold text-base">数据源与容灾</h2>
          </div>
          <div className="flex items-center justify-between py-3 border-t border-border/30">
            <div className="space-y-1">
              <span className="text-sm font-medium">雅虎财经 (YFinance) 轮询兜底</span>
              <p className="text-xs text-muted-foreground max-w-[500px]">当底层富途 OpenD 网关断连或达到频控限制时，系统自动切至外部 YF 数据源获取实时报价与基本面信息。</p>
            </div>
            {isLoading ? <Activity className="h-4 w-4 animate-spin text-muted-foreground" /> : (
              <Switch 
                checked={prefs.yfinanceFallbackEnabled} 
                onCheckedChange={(val) => updatePref('yfinanceFallbackEnabled', val)}
              />
            )}
          </div>
        </div>

        {/* 风控设置 */}
        <div className="glass-card rounded-xl p-5 border border-border/40">
          <div className="flex items-center gap-2 mb-4">
            <ShieldAlert className="h-5 w-5 text-red-400" />
            <h2 className="font-semibold text-base">实盘风控与杠杆</h2>
          </div>
          <div className="flex items-center justify-between py-3 border-t border-border/30">
            <div className="space-y-1">
              <span className="text-sm font-medium">全局默认最大杠杆率</span>
              <p className="text-xs text-muted-foreground max-w-[500px]">OMS 订单路由层将根据此参数对所有发单请求进行总资金敞口校验。</p>
            </div>
            <Select disabled={isLoading} value={String(prefs.defaultLeverage)} onValueChange={(val: any) => updatePref('defaultLeverage', parseFloat(val))}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="选择杠杆率" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">1.0x (无杠杆)</SelectItem>
                <SelectItem value="2">2.0x (两倍)</SelectItem>
                <SelectItem value="3">3.0x (激进)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  )
}