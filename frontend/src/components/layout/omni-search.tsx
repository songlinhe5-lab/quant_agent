import React, { useState, useEffect, useRef } from 'react';
import { Search, Loader2, TrendingUp, Landmark, LineChart, XCircle } from 'lucide-react';
import { apiClient } from '@/lib/api-client'; // 根据您的别名配置引入

interface SearchResult {
  symbol: string;
  name: string;
  type: string;
}

interface OmniSearchProps {
  /** 用户选中某个标的时触发的回调函数 */
  onSelect?: (symbol: string, name: string, type: string) => void;
}

export const OmniSearch: React.FC<OmniSearchProps> = ({ onSelect }) => {
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  
  const containerRef = useRef<HTMLDivElement>(null);

  // 1. 处理防抖逻辑 (Debounce)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300); // 300ms 防抖延迟

    return () => clearTimeout(timer);
  }, [query]);

  // 2. 监听防抖后的关键字并发起请求
  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    const fetchResults = async () => {
      setIsLoading(true);
      setIsOpen(true);
      try {
        const response = await apiClient.get('/market/search', {
          params: { q: debouncedQuery }
        });
        
        if (response.data && response.data.status === 'success') {
          setResults(response.data.data || []);
        } else {
          setResults([]);
        }
      } catch (error) {
        console.error("搜索请求失败:", error);
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    };

    fetchResults();
  }, [debouncedQuery]);

  // 3. 点击外部区域关闭下拉框
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 4. 根据资产类型返回对应图标
  const renderTypeIcon = (type: string) => {
    switch (type?.toUpperCase()) {
      case 'EQUITY':
      case 'STOCK':
        return <TrendingUp className="w-4 h-4 text-blue-400" />;
      case 'ETF':
        return <Landmark className="w-4 h-4 text-purple-400" />;
      case 'INDEX':
        return <LineChart className="w-4 h-4 text-emerald-400" />;
      default:
        return <TrendingUp className="w-4 h-4 text-slate-400" />;
    }
  };

  return (
    <div className="relative w-full max-w-md" ref={containerRef}>
      {/* 搜索框主体 */}
      <div className="relative group">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <Search className="h-4 w-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
        </div>
        <input
          type="text"
          className="w-full bg-white/50 dark:bg-slate-900/50 backdrop-blur-md border border-slate-200/50 dark:border-slate-700/50 text-slate-900 dark:text-slate-200 text-sm rounded-xl focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 block pl-10 p-2.5 transition-all shadow-sm placeholder-slate-400 dark:placeholder-slate-500"
          placeholder="搜索美股、港股、A股代码、拼音或公司名称..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            if (query.trim()) setIsOpen(true);
          }}
        />
        {/* 清除按钮 */}
        {query && (
          <button
            onClick={() => setQuery('')}
            className="absolute inset-y-0 right-0 pr-3 flex items-center hover:opacity-80"
          >
            <XCircle className="h-4 w-4 text-slate-400 dark:text-slate-500" />
          </button>
        )}
      </div>

      {/* 下拉结果面板 */}
      {isOpen && (
        <div className="absolute z-50 mt-2 w-full bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-slate-200 dark:border-slate-700/50 rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-top-2">
          {isLoading ? (
            <div className="flex items-center justify-center p-6 text-slate-500 dark:text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              <span className="text-sm">正在光速检索...</span>
            </div>
          ) : results.length > 0 ? (
            <ul className="max-h-[300px] overflow-y-auto py-2 custom-scrollbar">
              {results.map((item, index) => (
                <li 
                  key={`${item.symbol}-${index}`}
                  className="px-4 py-3 hover:bg-slate-100 dark:hover:bg-slate-800/50 cursor-pointer flex items-center justify-between group transition-colors"
                  onClick={() => {
                    setIsOpen(false);
                    setQuery(item.symbol);
                    
                    if (onSelect) {
                      onSelect(item.symbol, item.name, item.type);
                    }
                  }}
                >
                  <div className="flex items-center space-x-3">
                    <div className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg group-hover:bg-slate-200 dark:group-hover:bg-slate-700 transition-colors">
                      {renderTypeIcon(item.type)}
                    </div>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-200">{item.symbol}</span>
                      <span className="text-xs text-slate-500 line-clamp-1">{item.name}</span>
                    </div>
                  </div>
                  <span className="text-[10px] font-medium px-2 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 rounded-md">
                    {item.type}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-6 text-center text-sm text-slate-500">
              未找到与 "<span className="text-slate-700 dark:text-slate-300">{query}</span>" 相关的标的
            </div>
          )}
        </div>
      )}
    </div>
  );
};