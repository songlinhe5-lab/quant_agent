"use client"

import React, { useState, useEffect, forwardRef, useImperativeHandle } from 'react';
import { Plus, Trash2, Loader2, Gauge, X, Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api-client';
import { useConfirmDialog } from '@/components/confirm-dialog';
import { PCRatioTrendChart, VixCorrelationChart } from './sentiment-trend';

// --- Type Definitions ---
export interface SessionRecord {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface SessionSidebarProps {
  activeSessionId?: string;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
}

export interface SessionSidebarRef {
  fetchSessions: () => Promise<void>;
}

// --- Component ---
export const SessionSidebar = forwardRef<SessionSidebarRef, SessionSidebarProps>(
  ({ activeSessionId, onSelectSession, onNewChat }, ref) => {
    const { confirm } = useConfirmDialog();
    const [sessions, setSessions] = useState<SessionRecord[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [fgScore, setFgScore] = useState(74);
    const [showSentimentChart, setShowSentimentChart] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    // 模拟情绪指数在后台的实时跳动，增强静态组件生命力
    useEffect(() => {
      const timer = setInterval(() => {
         setFgScore(prev => Math.max(0, Math.min(100, prev + Math.floor(Math.random() * 5) - 2)));
      }, 15000);
      return () => clearInterval(timer);
    }, []);

    let fgLabel = '中性';
    let fgColor = 'text-amber-500';
    if (fgScore >= 75) { fgLabel = '极度贪婪'; fgColor = 'text-[#059669] dark:text-[#0ecb81]'; }
    else if (fgScore >= 55) { fgLabel = '贪婪'; fgColor = 'text-[#059669] dark:text-[#0ecb81]'; }
    else if (fgScore <= 25) { fgLabel = '极度恐惧'; fgColor = 'text-[#e11d48] dark:text-[#f6465d]'; }
    else if (fgScore <= 45) { fgLabel = '恐惧'; fgColor = 'text-[#e11d48] dark:text-[#f6465d]'; }

    const fetchSessions = async () => {
      setIsLoading(true);
      try {
        const res = await apiClient.get('/sessions');
        if (res.data?.status === 'success') {
          setSessions(res.data.data);
        }
      } catch (error) {
        console.error('⚠️ [Sidebar] 获取历史会话失败:', error);
      } finally {
        setIsLoading(false);
      }
    };

    // 暴露刷新方法给父组件，方便在新建对话或产生新消息后刷新列表
    useImperativeHandle(ref, () => ({
      fetchSessions,
    }));

    useEffect(() => {
      fetchSessions();
    }, []);

    const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
      e.stopPropagation(); // 阻止冒泡，防止触发选中会话的事件
      const ok = await confirm({ title: '删除会话', description: '确定要彻底删除该会话记录吗？该操作同时清理冷热数据库，无法恢复。', confirmLabel: '永久删除' })
      if (!ok) return;

      try {
        const res = await apiClient.delete(`/sessions/${sessionId}`);
        if (res.data?.status === 'success') {
          // UI 层乐观更新移除
          setSessions(prev => prev.filter(s => s.session_id !== sessionId));
          
          // 如果删掉的是当前正打开的对话，自动触发新建回退
          if (activeSessionId === sessionId) {
            onNewChat();
          }
        }
      } catch (error) {
        console.error('⚠️ [Sidebar] 删除会话失败:', error);
      }
    };

    const formatDate = (dateStr: string) => {
      // 💡 修复：后端返回的无状态 ISO 时间默认是 UTC，需强制追加 'Z' 触发前端本地时区转换
      let str = dateStr;
      if (str && !str.endsWith('Z') && !str.match(/[+-]\d{2}:\d{2}$/)) {
        str += 'Z';
      }
      const date = new Date(str);
      return date.toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    };

    const filteredSessions = sessions.filter(session => 
      session.title.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
      <aside className="w-72 h-full flex flex-col bg-white/80 dark:bg-zinc-950/80 backdrop-blur-xl border-r border-border/40 shrink-0 transition-colors">
        {/* 侧边栏头部：新建对话 */}
        <div className="p-4 border-b border-border/40 space-y-3">
          <button
            onClick={onNewChat}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 hover:shadow-[0_0_15px_rgba(16,185,129,0.15)] transition-all duration-300 font-medium"
          >
            <Plus className="w-4 h-4" />
            新建推演 (New Chat)
          </button>
          
          {/* 搜索框 */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索推演记录..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-secondary/30 border border-border/50 rounded-lg pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all text-foreground placeholder:text-muted-foreground"
            />
          </div>
        </div>

        {/* 历史会话列表 */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
          {isLoading ? (
            <div className="flex justify-center items-center py-10">
              <Loader2 className="w-6 h-6 animate-spin text-primary/50" />
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="text-center py-10 text-muted-foreground text-sm">
              {searchQuery ? '无匹配搜索结果' : '暂无历史推演记录'}
            </div>
          ) : (
            filteredSessions.map(session => (
              <div
                key={session.session_id}
                onClick={() => onSelectSession(session.session_id)}
                className={cn(
                  "group relative p-3 rounded-xl cursor-pointer border transition-all duration-300",
                  activeSessionId === session.session_id
                    ? "bg-primary/10 border-primary/30 shadow-[0_0_10px_rgba(var(--primary),0.1)]"
                    : "bg-transparent border-transparent hover:bg-slate-100 dark:hover:bg-white/5 hover:border-slate-200 dark:hover:border-white/10"
                )}
              >
                {/* 标题与消息数 */}
                <div className="flex justify-between items-start mb-1.5 pr-6">
                  <h3 className="text-sm font-medium text-slate-800 dark:text-gray-200 truncate pr-2 transition-colors" title={session.title}>
                    {session.title}
                  </h3>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-800 text-slate-500 dark:text-gray-400 shrink-0 transition-colors">
                    {session.message_count} 条
                  </span>
                </div>

                {/* 时间与删除按钮 */}
                <div className="flex justify-between items-center text-xs text-slate-500 dark:text-gray-500 font-mono transition-colors">
                  <span>{formatDate(session.updated_at)}</span>
                  <button
                    onClick={(e) => handleDelete(e, session.session_id)}
                    className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-red-400 hover:bg-red-400/20 transition-all duration-300 absolute right-2 top-1/2 -translate-y-1/2"
                    title="删除彻底清除记忆"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
        
        {/* 底部实时情绪仪表 */}
        <div 
          className="p-4 border-t border-border/40 bg-slate-50/50 dark:bg-black/20 shrink-0 cursor-pointer hover:bg-slate-100/50 dark:hover:bg-white/5 transition-colors group"
          onClick={() => setShowSentimentChart(true)}
          title="点击查看近30天情绪趋势图"
        >
          <div className="flex items-center gap-1.5 mb-2">
            <Gauge className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
            <span className="text-xs font-semibold text-muted-foreground group-hover:text-foreground transition-colors uppercase tracking-wider">市场情绪 (F&G)</span>
          </div>
          <div className="flex items-end justify-between mb-2">
            <div className="flex items-baseline gap-1.5">
              <span className={cn("text-xl font-bold font-mono tabular-nums leading-none transition-colors duration-500", fgColor)}>{fgScore}</span>
              <span className={cn("text-[10px] font-bold uppercase transition-colors duration-500", fgColor)}>{fgLabel}</span>
            </div>
          </div>
          <div className="relative h-1.5 w-full rounded-full bg-gradient-to-r from-[#e11d48] via-amber-500 to-[#059669] dark:from-[#f6465d] dark:to-[#0ecb81] opacity-90 overflow-hidden">
             <div className="absolute top-0 bottom-0 w-1 bg-white shadow-[0_0_5px_rgba(255,255,255,1)] rounded-full transition-all duration-1000 ease-out" style={{ left: `${fgScore}%`, transform: 'translateX(-50%)' }} />
          </div>
          <div className="flex justify-between text-[8px] text-muted-foreground uppercase font-bold mt-1">
            <span>恐惧</span><span>贪婪</span>
          </div>
        </div>

        {/* 情绪趋势图弹窗 (Dialog) */}
        {showSentimentChart && (
          <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200" onClick={() => setShowSentimentChart(false)}>
            <div className="w-full max-w-6xl relative" onClick={e => e.stopPropagation()}>
              <button 
                onClick={() => setShowSentimentChart(false)} 
                className="absolute -top-3 -right-3 z-20 p-1.5 bg-white dark:bg-zinc-800 text-muted-foreground hover:text-foreground hover:bg-slate-100 dark:hover:bg-zinc-700 rounded-full shadow-xl border border-border/50 transition-colors"
                title="关闭"
              >
                <X className="h-4 w-4" />
              </button>
              <div className="w-full shadow-2xl rounded-xl overflow-hidden bg-slate-50 dark:bg-zinc-950/80 backdrop-blur-xl border border-border/40 p-4">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[450px]">
                  <div className="h-full [&>div]:!h-full">
                    <PCRatioTrendChart />
                  </div>
                  <div className="h-full [&>div]:!h-full">
                    <VixCorrelationChart />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 注入组件专属的极简滚动条样式 */}
        <style dangerouslySetInnerHTML={{__html: `
          .custom-scrollbar::-webkit-scrollbar { width: 4px; }
          .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
          .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 4px; }
          .custom-scrollbar:hover::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.2); }
        `}} />
      </aside>
    );
  }
);

SessionSidebar.displayName = 'SessionSidebar';