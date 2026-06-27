import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/auth-context';
import { Brain, Lock, User, Loader2, AlertCircle, CheckCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // 默认填入后端刚初始化的管理员账号密码
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  // 获取用户被拦截前的目标路径（通过 URL 参数 ?from=xxx 传递），登录后原路送回
  const from = searchParams?.get('from') || '/';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }

    setError('');
    setLoading(true);

    try {
      await login(username, password);
      // 登录成功，触发成功动画状态，并延迟 800ms 后再跳转
      setSuccess(true);
      setTimeout(() => {
        navigate(from, { replace: true });
      }, 800);
    } catch (err: any) {
      setError(err.response?.data?.detail || '无法连接到后端，请检查用户名或网络。');
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 transition-colors duration-300 overflow-hidden">
      {/* 背景氛围装饰 */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] bg-violet-500/20 dark:bg-violet-600/10 blur-[120px] rounded-full pointer-events-none" />

      <div className="relative w-full max-w-md p-8 glass-card rounded-2xl shadow-2xl border border-border/40 bg-white/80 dark:bg-[oklch(0.10_0.01_270)]/90 backdrop-blur-xl transition-colors duration-300">

        {/* Logo 区域 */}
        <div className="flex flex-col items-center mb-8">
          <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-4 shadow-inner">
            <Brain className="h-8 w-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Quant Agent</h1>
          <p className="text-sm text-muted-foreground mt-1">AI 驱动的极客量化终端</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-semibold text-muted-foreground uppercase ml-1">用户名 / Username</label>
            <div className="relative flex items-center">
              <User className="absolute left-3 h-4 w-4 text-muted-foreground" />
              <input type="text" required value={username} onChange={(e) => setUsername(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-secondary/40 border border-border/50 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all text-sm font-mono"
                placeholder="admin" />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-muted-foreground uppercase ml-1">密码 / Password</label>
            <div className="relative flex items-center">
              <Lock className="absolute left-3 h-4 w-4 text-muted-foreground" />
              <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-secondary/40 border border-border/50 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all text-sm font-mono"
                placeholder="••••••••" />
            </div>
          </div>

          <Button
            type="submit"
            disabled={loading || success}
            className={`w-full h-11 text-sm font-bold mt-2 shadow-lg transition-all duration-300 ${success ? 'bg-emerald-500 hover:bg-emerald-600 text-white shadow-emerald-500/25' : 'hover:shadow-primary/25'}`}
          >
            {success ? <><CheckCircle className="h-4 w-4 mr-2 animate-in zoom-in" />验证通过，正在进入...</> :
               loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />正在验证枢纽身份...</> :
               '进入终端 (Access Terminal)'}
          </Button>
        </form>

        <p className="text-center text-[10px] text-muted-foreground mt-8">Secure Access Control · v2.4.1</p>
      </div>
    </div>
  );
}
