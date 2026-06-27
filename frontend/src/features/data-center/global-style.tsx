import React from 'react';

export function GlobalStyle() {
  return (
    <style dangerouslySetInnerHTML={{ __html: `
      @keyframes flash-green-pulse{0%,100%{background-color:transparent}20%{background-color:rgba(14,203,129,0.25)}}
      @keyframes flash-red-pulse{0%,100%{background-color:transparent}20%{background-color:rgba(246,70,93,0.25)}}
      .animate-flash-green{animation:flash-green-pulse .8s ease-out}
      .animate-flash-red{animation:flash-red-pulse .8s ease-out}
      
      /* 丝滑的新闻插入淡入下压动画 */
      @keyframes news-slide-down {
        0% { opacity: 0; transform: translateY(-15px); grid-template-rows: 0fr; }
        100% { opacity: 1; transform: translateY(0); grid-template-rows: 1fr; }
      }
      .animate-news-item {
        display: grid;
        opacity: 0;
        animation: news-slide-down 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
      }

      /* 极简暗黑风滚动条 */
      .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
      .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
      .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(156, 163, 175, 0.3); border-radius: 4px; }
      .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(156, 163, 175, 0.5); }
    `.replace(/\n\s*/g, '') }} />
  );
}