import React, { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom';
import { OmniSearch } from './omni-search';
import { useMarketStore } from '@/stores/marketStore';
import { useTheme } from 'next-themes';
import { Sun, Moon, LogOut, User, Settings, CreditCard, Bell, Cpu, Database } from 'lucide-react';
import { useAuth } from '@/contexts/auth-context';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { apiClient } from '@/lib/api-client';
import { cn } from '@/lib/utils';
import { useI18n, type DictionaryKey } from '@/contexts/i18n';

/* ── 动态科幻 SVG Logo 组件 ─────────────────────────────────────── */
const SciFiLogo = () => (
  <div className="relative flex items-center justify-center w-8 h-8 mr-3 flex-shrink-0">
    {/* 外层顺时针旋转六边形 */}
    <svg viewBox="0 0 100 100" className="absolute inset-0 w-full h-full animate-[spin_10s_linear_infinite]">
      <defs>
        <linearGradient id="scifi-grad-1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
        <filter id="glow-1" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>
      <polygon points="50,5 89,27.5 89,72.5 50,95 11,72.5 11,27.5" fill="none" stroke="url(#scifi-grad-1)" strokeWidth="4" filter="url(#glow-1)" />
    </svg>
    {/* 内层逆时针旋转三角形 */}
    <svg viewBox="0 0 100 100" className="absolute inset-0 w-full h-full animate-[spin_7s_linear_infinite_reverse]">
       <polygon points="50,20 80,75 20,75" fill="none" stroke="#22d3ee" strokeWidth="2" opacity="0.8" />
    </svg>
    {/* 核心脉冲发光圆点 */}
    <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.9)]" />
  </div>
);

/* ── 全局资产跑马灯组件 ─────────────────────────────────────────────────── */
function TickerTape() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState<any[]>([]);

  useEffect(() => {
    let isMounted = true;
    const fetchAssets = async () => {
      try {
        const res = await apiClient.get('/macro/assets');
        if (isMounted && res.data?.status === 'success') {
          setAssets(res.data.data.macroAssets || []);
        }
      } catch (e) { /* ignore network error */ }
    };
    fetchAssets();
    const iv = setInterval(fetchAssets, 60000); // 1分钟轮询，紧跟后台 Redis 缓存节奏
    return () => { isMounted = false; clearInterval(iv); };
  }, []);

  if (assets.length === 0) return null;

  // 将数组复制一份以实现首尾相接的无缝无限滚动
  const displayAssets = [...assets, ...assets];

  return (
    <div className="relative flex overflow-hidden h-9 items-center bg-slate-100/50 dark:bg-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-800 mask-edges w-full">
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes ticker-roll { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }
        .animate-ticker { animation: ticker-roll 35s linear infinite; will-change: transform; }
        .animate-ticker:hover { animation-play-state: paused; }
        .mask-edges { -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent); mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent); }
      `}} />
      <div className="flex animate-ticker items-center w-max">
        {displayAssets.map((asset, i) => (
          <div key={i} onClick={() => navigate(`/market/${asset.symbol}`)} className="flex items-center gap-2 px-4 border-r border-slate-300 dark:border-slate-700 last:border-0 cursor-pointer hover:bg-slate-200/50 dark:hover:bg-slate-800/50 transition-colors h-9 whitespace-nowrap">
            <span className="text-[11px] font-bold text-slate-700 dark:text-slate-300">{asset.symbol}</span>
            <span className={cn("text-[11px] font-mono tabular-nums", asset.change >= 0 ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]")}>{asset.value.toFixed(2)}</span>
            <span className={cn("text-[10px] font-mono font-bold tabular-nums", asset.change >= 0 ? "text-[#059669] dark:text-[#0ecb81]" : "text-[#e11d48] dark:text-[#f6465d]")}>{asset.change >= 0 ? '+' : ''}{asset.change.toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 系统资源监控组件 ───────────────────────────────────────────── */
function SystemMetrics() {
  const [cpu, setCpu] = useState(12);
  const [mem, setMem] = useState(45);

  useEffect(() => {
    // 模拟实时系统资源跳动 (若有真实 API 可无缝替换为真实数据)
    const iv = setInterval(() => {
      setCpu(prev => Math.min(99, Math.max(5, prev + (Math.random() * 14 - 7))));
      setMem(prev => Math.min(99, Math.max(20, prev + (Math.random() * 6 - 3))));
    }, 2000);
    return () => clearInterval(iv);
  }, []);

  const getColor = (val: number) => val > 80 ? 'text-red-500 bg-red-500' : val > 60 ? 'text-amber-500 bg-amber-500' : 'text-emerald-500 bg-emerald-500';

  return (
    <div className="hidden xl:flex items-center gap-3 px-3 py-1.5 bg-slate-100 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-lg shrink-0">
      <div className="flex flex-col gap-0.5 w-12" title={`CPU 负载: ${cpu.toFixed(1)}%`}>
        <div className="flex items-center justify-between"><Cpu className="w-3 h-3 text-muted-foreground" /><span className={cn("text-[9px] font-mono font-bold", getColor(cpu).split(' ')[0])}>{cpu.toFixed(0)}%</span></div>
        <div className="h-1 w-full bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden"><div className={cn("h-full rounded-full transition-all duration-500", getColor(cpu).split(' ')[1])} style={{ width: `${cpu}%` }} /></div>
      </div>
      <div className="w-px h-5 bg-slate-300 dark:bg-slate-700" />
      <div className="flex flex-col gap-0.5 w-12" title={`内存占用: ${mem.toFixed(1)}%`}>
        <div className="flex items-center justify-between"><Database className="w-3 h-3 text-muted-foreground" /><span className={cn("text-[9px] font-mono font-bold", getColor(mem).split(' ')[0])}>{mem.toFixed(0)}%</span></div>
        <div className="h-1 w-full bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden"><div className={cn("h-full rounded-full transition-all duration-500", getColor(mem).split(' ')[1])} style={{ width: `${mem}%` }} /></div>
      </div>
    </div>
  );
}

export const Navbar: React.FC = () => {
  const navigate = useNavigate();
  const setCurrentTicker = useMarketStore((state: any) => state.setCurrentTicker);
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const { user, logout } = useAuth();
  const { locale, setLocale, t } = useI18n();

  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // 避免在 hydration 期间出现 UI 不匹配的问题
  useEffect(() => setMounted(true), []);

  // 点击外部自动关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSearchSelect = (symbol: string, name: string, type: string) => {
    // 1. 同步更新 Zustand 全局状态
    setCurrentTicker(symbol, name, type);

    // 2. 强制路由跳转到行情仪表盘页面 (无论当前在哪个页面)
    navigate(`/market/${symbol}`);
  };

  return (
    <nav className="flex items-center justify-between pl-2 pr-6 h-14 shrink-0 bg-white/80 dark:bg-slate-950/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 sticky top-0 z-50 transition-colors duration-300 w-full">

      {/* 左侧 Logo 区 */}
      <div className="flex items-center flex-shrink-0">
        {/* 侧边栏唤出按钮 */}
        <SidebarTrigger className="-ml-2 mr-4" />
        <div
          className="flex items-center cursor-pointer group"
          onClick={() => navigate('/')}
        >
          <SciFiLogo />
          <span className="text-xl font-black tracking-widest uppercase text-transparent bg-clip-text bg-gradient-to-r from-blue-500 via-cyan-400 to-purple-500 group-hover:opacity-80 transition-opacity">
            Quant Agent
          </span>
        </div>
      </div>

      {/* 中间跑马灯 (独占 C 位，自动拉伸) */}
      <div className="flex-1 hidden lg:block overflow-hidden mx-8 max-w-4xl">
        <TickerTape />
      </div>

      {/* 右侧功能区（搜索框 + 工具 + 通知 + 用户头像等） */}
      <div className="flex items-center space-x-3 text-sm text-slate-600 dark:text-slate-400 font-medium flex-shrink-0">

        {/* 搜索框移到右侧，为居中的跑马灯腾出空间 */}
        <div className="w-56 xl:w-72 hidden md:block mr-2">
          <OmniSearch onSelect={handleSearchSelect} />
        </div>

        <SystemMetrics />

        {mounted && (
          <>
            {/* 语言切换按钮 */}
            <button
              onClick={() => setLocale(locale === 'zh-CN' ? 'en-US' : 'zh-CN')}
              className="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus:outline-none text-xs font-bold font-mono text-slate-600 dark:text-slate-400"
              title="切换语言 / Switch Language"
            >
              {locale === 'zh-CN' ? 'EN' : '中'}
            </button>

            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus:outline-none"
              title="切换主题"
            >
              {theme === 'dark' ? (
                <Sun className="w-5 h-5 hover:text-amber-400 transition-colors" />
              ) : (
                <Moon className="w-5 h-5 hover:text-blue-500 transition-colors" />
              )}
            </button>
          </>
        )}

        {user ? (
          <div className="relative flex items-center pl-2 ml-2 border-l border-slate-200 dark:border-slate-800" ref={userMenuRef}>
            <button
              onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
              className="flex items-center gap-2 hover:bg-slate-100 dark:hover:bg-slate-800 p-1.5 rounded-lg transition-colors focus:outline-none"
            >
              <div className="h-8 w-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm shadow-sm flex-shrink-0">
                {user.username.charAt(0).toUpperCase()}
              </div>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {user.username}
              </span>
            </button>

            {/* 下拉悬浮卡片 */}
            {isUserMenuOpen && (
              <div className="absolute top-full right-0 mt-1 w-56 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-lg overflow-hidden z-50 animate-in fade-in slide-in-from-top-2">
                <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">{user.username}</p>
                  <p className="text-xs text-slate-500 truncate">{user.email || 'admin@quant.local'}</p>
                </div>
                <div className="p-1.5">
                  <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
                    <User className="h-4 w-4" />{t('userMenu.profile' as DictionaryKey) || '个人中心'}
                  </button>
                  <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
                    <CreditCard className="h-4 w-4" />{t('userMenu.billing' as DictionaryKey) || '账单与订阅'}
                  </button>
                  <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
                    <Bell className="h-4 w-4" />{t('userMenu.notifications' as DictionaryKey) || '消息通知'}
                  </button>
                  <button
                    onClick={() => { setIsUserMenuOpen(false); navigate('/settings'); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
                  >
                    <Settings className="h-4 w-4" />{t('userMenu.settings' as DictionaryKey) || '系统设置'}
                  </button>
                </div>
                <div className="p-1.5 border-t border-slate-200 dark:border-slate-800">
                  <button
                    onClick={logout}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-colors"
                  >
                    <LogOut className="h-4 w-4" />{t('userMenu.logout' as DictionaryKey) || '退出登录'}
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </nav>
  );
};
