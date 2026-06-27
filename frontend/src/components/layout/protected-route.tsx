import * as React from 'react';
import { useEffect } from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from '@/contexts/auth-context';
import { Loader2 } from 'lucide-react';

export const ProtectedRoute = () => {
  const { user, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    // 如果认证状态加载完毕，且当前没有用户，且不在登录页，则触发拦截跳转
    if (!isLoading && !user && location.pathname !== '/login') {
      navigate(`/login?from=${encodeURIComponent(location.pathname || '/')}`, { replace: true });
    }
  }, [user, isLoading, location.pathname, navigate]);

  // 如果正在检查登录状态，或者未登录被拦截但还未跳转走，显示全屏 Loading，防止原本的数据画面闪烁泄露
  if (isLoading || (!user && location.pathname !== '/login')) {
    return (
      <div className="fixed inset-0 z-[100] bg-slate-50 dark:bg-slate-950 flex flex-col overflow-hidden">
        {/* 顶部导航栏骨架 */}
        <div className="h-14 border-b border-border/30 px-6 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-8">
            <div className="h-6 w-32 bg-primary/20 rounded animate-pulse" />
            <div className="h-8 w-64 bg-secondary/60 rounded-xl animate-pulse hidden md:block" />
          </div>
          <div className="flex items-center gap-4">
            <div className="h-8 w-8 bg-secondary/60 rounded-lg animate-pulse" />
            <div className="h-8 w-8 bg-secondary/60 rounded-full animate-pulse" />
          </div>
        </div>
        
        {/* 主体内容骨架 (量化终端网格布局) */}
        <div className="flex-1 p-4 grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-4">
          <div className="flex flex-col gap-4">
            {/* 核心业务/图表区骨架 */}
            <div className="flex-1 bg-secondary/30 rounded-xl border border-border/20 animate-pulse flex items-center justify-center">
              <div className="flex flex-col items-center gap-3 opacity-50">
                <Loader2 className="h-8 w-8 text-primary animate-spin" />
                <p className="text-xs text-muted-foreground font-mono">Verifying Access...</p>
              </div>
            </div>
            {/* 底部区骨架 */}
            <div className="h-48 bg-secondary/30 rounded-xl border border-border/20 animate-pulse hidden md:block" />
          </div>
          
          {/* 右侧面板/订单簿骨架 */}
          <div className="flex flex-col gap-4 hidden lg:flex">
            <div className="h-2/3 bg-secondary/30 rounded-xl border border-border/20 animate-pulse" />
            <div className="flex-1 bg-secondary/30 rounded-xl border border-border/20 animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  // 验证通过，正常渲染受保护的业务组件
  return <Outlet />;
};
