import React, { useState, useEffect } from 'react';
import { getRelativeTimeText } from '@/utils/format';
import { RefreshCw } from 'lucide-react';

// 💡 新增 actual 属性，用于判断数据是否已真实下发
export default function EventCountdown({ dateIso, actual = null, onRefresh }) {
  const [countdownText, setCountdownText] = useState(getRelativeTimeText(dateIso));
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    // 首次渲染后，每 60 秒重新计算一次倒计时
    const timer = setInterval(() => {
      setCountdownText(getRelativeTimeText(dateIso));
    }, 60000); 

    // 组件卸载时清理定时器防止内存泄漏
    return () => clearInterval(timer);
  }, [dateIso]);

  const isPast = countdownText === "已发布";
  const isUrgent = countdownText.includes("分钟"); // 剩不到 1 小时
  const hasActualData = actual !== null && actual !== undefined && actual !== "";

  // 手动触发刷新，带防抖与事件冒泡拦截
  const handleRefreshClick = async (e) => {
    if (e) e.stopPropagation();
    if (!onRefresh || isRefreshing) return;
    
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
    }
  };

  // 💡 决定最终显示的文本和动态样式
  let displayText = countdownText;
  let containerClass = "bg-indigo-500/20 text-indigo-400"; // 默认紫色：常规倒计时

  if (isPast) {
    if (hasActualData) {
      displayText = "已发布";
      containerClass = "bg-slate-700/50 text-slate-400"; // 灰色：数据已出炉
    } else {
      displayText = "等待公布中...";
      // 如果传入了 onRefresh，则允许点击交互；否则仅展示呼吸灯
      containerClass = `bg-amber-500/20 text-amber-400 ${onRefresh ? 'cursor-pointer hover:bg-amber-500/30' : 'animate-pulse'}`; 
    }
  } else if (isUrgent) {
    containerClass = "bg-red-500/20 text-red-400 animate-pulse"; // 红色呼吸灯：即将发布
  }

  return (
    <span 
      onClick={(isPast && !hasActualData && onRefresh) ? handleRefreshClick : undefined}
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold transition-colors duration-300 ${containerClass}`}
      title={(isPast && !hasActualData && onRefresh) ? "点击手动刷新获取最新数据" : undefined}
    >
      {isPast && !hasActualData && onRefresh && (
        <RefreshCw className={`h-3 w-3 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
      )}
      {displayText}
    </span>
  );
}
