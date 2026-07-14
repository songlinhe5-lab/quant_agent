'use client'

import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/use-toast'
import { apiClient } from '@/lib/api-client'
import { Loader2, Shield, Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TradingModeSwitcher } from '@/components/layout/trading-mode-switcher'

type SettingsContentProps = {
  className?: string
  compact?: boolean
}

/** 设置表单本体：页面与右侧抽屉共用 */
export function SettingsContent({ className, compact }: SettingsContentProps) {
  return (
    <div className={cn(compact ? 'space-y-4' : 'p-6 space-y-6', className)}>
      {!compact && <h1 className="text-2xl font-bold">系统设置</h1>}

      <Tabs defaultValue="account" className="space-y-4">
        <TabsList className={cn(compact && 'flex flex-wrap h-auto gap-1')}>
          <TabsTrigger value="account">
            <Shield className="h-4 w-4 mr-2" />
            账户安全
          </TabsTrigger>
          <TabsTrigger value="general">通用设置</TabsTrigger>
          <TabsTrigger value="appearance">外观主题</TabsTrigger>
          <TabsTrigger value="notifications">通知提醒</TabsTrigger>
          <TabsTrigger value="api">API 配置</TabsTrigger>
        </TabsList>

        <TabsContent value="account" className="space-y-4">
          <ChangePasswordCard />
        </TabsContent>

        <TabsContent value="general" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>运行模式</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-muted-foreground text-sm">
                SANDBOX / PAPER / LIVE（与顶栏联动；PAPER↔LIVE 需二次确认）
              </p>
              <TradingModeSwitcher alwaysShow />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>通用设置</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground text-sm">
                推送通道等项将在后续迭代接入。当前占位。
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="appearance" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>外观主题</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground text-sm">主题设置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>通知提醒</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground text-sm">通知设置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="api" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>API 配置</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground text-sm">API 配置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ChangePasswordCard() {
  const { toast } = useToast()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showOld, setShowOld] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!oldPassword || !newPassword || !confirmPassword) {
      toast({ title: '请填写完整', description: '所有字段都是必填的', variant: 'destructive' })
      return
    }

    if (newPassword.length < 6) {
      toast({ title: '密码过短', description: '新密码至少需要 6 个字符', variant: 'destructive' })
      return
    }

    if (newPassword !== confirmPassword) {
      toast({ title: '密码不匹配', description: '新密码和确认密码不一致', variant: 'destructive' })
      return
    }

    if (oldPassword === newPassword) {
      toast({ title: '密码相同', description: '新密码不能与旧密码相同', variant: 'destructive' })
      return
    }

    setIsLoading(true)
    try {
      await apiClient.post('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      })

      toast({ title: '密码修改成功', description: '请使用新密码重新登录' })
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => {
        window.location.href = '/login'
      }, 2000)
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '密码修改失败，请检查旧密码是否正确'
      toast({ title: '修改失败', description: message, variant: 'destructive' })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="h-5 w-5" />
          修改密码
        </CardTitle>
        <CardDescription>定期修改密码可以提高账户安全性</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
          <div className="space-y-2">
            <Label htmlFor="old-password">当前密码</Label>
            <div className="relative">
              <Input
                id="old-password"
                type={showOld ? 'text' : 'password'}
                placeholder="输入当前密码"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                disabled={isLoading}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowOld(!showOld)}
              >
                {showOld ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-password">新密码</Label>
            <div className="relative">
              <Input
                id="new-password"
                type={showNew ? 'text' : 'password'}
                placeholder="至少 6 个字符"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={isLoading}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowNew(!showNew)}
              >
                {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm-password">确认新密码</Label>
            <div className="relative">
              <Input
                id="confirm-password"
                type={showConfirm ? 'text' : 'password'}
                placeholder="再次输入新密码"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isLoading}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowConfirm(!showConfirm)}
              >
                {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <Button type="submit" disabled={isLoading} className="w-full">
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                修改中...
              </>
            ) : (
              '修改密码'
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
