import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export default function SettingsPage() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">系统设置</h1>
      
      <Tabs defaultValue="general" className="space-y-4">
        <TabsList>
          <TabsTrigger value="general">通用设置</TabsTrigger>
          <TabsTrigger value="appearance">外观主题</TabsTrigger>
          <TabsTrigger value="notifications">通知提醒</TabsTrigger>
          <TabsTrigger value="api">API 配置</TabsTrigger>
        </TabsList>
        
        <TabsContent value="general" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>通用设置</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">通用设置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="appearance" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>外观主题</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">主题设置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="notifications" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>通知提醒</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">通知设置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="api" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>API 配置</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">API 配置内容待完善...</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
