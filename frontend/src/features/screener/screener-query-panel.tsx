'use client'

import React from 'react'
import { Search, Sparkles, CornerDownLeft, History, RefreshCw, Database, ChevronRight, Zap, BellRing, Code2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getZhLabel } from './shared'
import { useScreenerContext } from './screener-context'
import { apiClient } from '@/lib/api-client'

export function ScreenerQueryPanel() {
  const {
    nlpQuery, setNlpQuery, dslQuery, setDslQuery, showHistory, setShowHistory,
    history, setHistory, placeholderText, displayPrompts, refreshPrompts,
    isLoading, progress, scanStatus, handleTranslate, showRawDsl, setShowRawDsl, handleSubscribe
  } = useScreenerContext()

  const parseVal = (v: any) => {
    const str = String(v).replace(/[+%]/g, '')
    let num = parseFloat(str)
    if (str.includes('万亿')) num *= 1e12
    else if (str.includes('亿')) num *= 1e8
    else if (str.includes('万')) num *= 1e4
    else if (str.includes('K')) num *= 1e3
    else if (str.includes('M')) num *= 1e6
    else if (str.includes('B')) num *= 1e9
    else if (str.includes('T')) num *= 1e12
    return isNaN(num) ? 0 : num
  }

  return (
    <div className="glass-card rounded-xl overflow-hidden transition-colors duration-300 border border-border/40 shadow-sm relative">
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-1.5 text-primary">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            <span className="text-sm font-semibold tracking-wide">AI 语义筛选</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground font-mono bg-secondary/50 px-2 py-0.5 rounded border border-border/30 hidden sm:inline-block">全市场 5,832 只 · 毫秒级扫描</span>
            <div className="relative">
              <button onClick={() => setShowHistory(!showHistory)} onBlur={() => setTimeout(() => setShowHistory(false), 200)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary transition-colors bg-secondary/30 hover:bg-secondary/60 px-2 py-0.5 rounded border border-border/50">
                <History className="h-3 w-3" /> 历史记录
              </button>
              {showHistory && (
                <div className="absolute right-0 top-full mt-1 w-64 bg-card border border-border/50 rounded-lg shadow-xl z-50 overflow-hidden animate-in fade-in slide-in-from-top-2">
                  <div className="px-3 py-1.5 border-b border-border/30 bg-secondary/20 flex justify-between items-center">
                     <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">最近查询记录</span>
                     {history.length > 0 && <button onMouseDown={(e) => { e.preventDefault(); setHistory([]); localStorage.removeItem('quant_screener_history'); apiClient.post('/screener/history', { history: [] }).catch(()=>{}); }} className="text-[9px] text-red-500 hover:underline">清空</button>}
                  </div>
                  <div className="max-h-48 overflow-y-auto custom-scrollbar p-1">
                    {history.length === 0 ? (
                      <div className="text-center text-[10px] text-muted-foreground py-4">暂无历史记录</div>
                    ) : history.map((h, i) => (
                      <button key={i} onMouseDown={(e) => { e.preventDefault(); setNlpQuery(h.nlp); setDslQuery(h.dsl); setShowHistory(false); handleTranslate(h.nlp); }} className="w-full text-left px-2 py-1.5 hover:bg-secondary/50 rounded transition-colors flex flex-col gap-0.5 group">
                        <span className="text-[11px] text-foreground truncate font-medium group-hover:text-primary">{h.nlp}</span>
                        <span className="text-[9px] text-muted-foreground font-mono truncate">{new Date(h.time).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="relative group">
          <div className="absolute left-3 top-3.5 text-muted-foreground group-focus-within:text-primary transition-colors">
            <Search className="h-4 w-4" />
          </div>
          <textarea id="nlp-query" placeholder={placeholderText} className="w-full pl-9 pr-12 py-3 rounded-xl bg-background border border-border/60 hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary/30 outline-none transition-all duration-300 text-sm font-mono resize-none leading-relaxed shadow-sm dark:bg-black/20" rows={3} value={nlpQuery} onChange={(e) => { setNlpQuery(e.target.value); setDslQuery('') }} onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleTranslate() } }} aria-label="输入自然语言选股条件" />
          <div className="absolute right-2 bottom-2 flex items-center gap-2">
            {isLoading && progress > 0 && (
              <div className="flex items-center gap-1.5 mr-1 bg-background/80 backdrop-blur px-2 py-1 rounded-md">
                <span className="text-[10px] text-primary font-mono animate-pulse">{scanStatus}</span>
                <span className="text-[10px] font-mono text-primary font-bold w-7 text-right">{Math.round(progress)}%</span>
              </div>
            )}
            <Button size="sm" className="h-7 px-3 gap-1.5 text-[11px] font-bold rounded-lg shadow-sm" onClick={handleTranslate} disabled={!nlpQuery.trim() || isLoading}>
              {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CornerDownLeft className="h-3.5 w-3.5" />}
              {isLoading ? '扫描中...' : '生成策略'}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1 max-h-48 overflow-y-auto custom-scrollbar pr-2">
          <span className="text-[10px] text-muted-foreground font-medium py-1">💡 灵感：</span>
          {displayPrompts.map((prompt, idx) => (
            <button key={idx} onClick={() => { setNlpQuery(prompt); setDslQuery('') }} className="text-[10px] px-2.5 py-1 rounded-full bg-secondary/60 hover:bg-primary/10 text-muted-foreground hover:text-primary border border-transparent hover:border-primary/20 transition-all cursor-pointer text-left">
              {prompt}
            </button>
          ))}
          <button onClick={refreshPrompts} className="text-[10px] px-2 py-1 rounded text-muted-foreground hover:text-primary transition-colors flex items-center gap-1 ml-auto" title="换一批灵感">
            <RefreshCw className="h-3 w-3" /> 换一批
          </button>
        </div>

        {dslQuery && (
          <div className="p-3 mt-2 rounded-lg bg-violet-500/5 dark:bg-violet-500/10 border border-violet-500/20 transition-colors duration-300 animate-in fade-in slide-in-from-top-2">
            {(() => {
              try {
                const data = JSON.parse(dslQuery);
                return (
                  <div className="flex flex-col gap-2.5">
                    {data.rag_rules && data.rag_rules.length > 0 && (
                      <details className="group bg-background/50 rounded-lg border border-border/50 shadow-sm overflow-hidden">
                        <summary className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider flex items-center gap-1.5 p-2.5 cursor-pointer select-none hover:bg-secondary/20 transition-colors list-none [&::-webkit-details-marker]:hidden">
                          <Database className="h-3 w-3 text-indigo-500 dark:text-indigo-400" />RAG 知识库召回依据：<ChevronRight className="h-3 w-3 ml-auto transition-transform duration-200 group-open:rotate-90" />
                        </summary>
                        <div className="px-2.5 pb-2.5 pt-0 border-t border-border/30 mt-1">
                          <ul className="space-y-1.5 mt-2">
                            {data.rag_rules.map((rule: string, i: number) => (
                              <li key={i} className="text-[10px] text-muted-foreground/80 font-mono leading-relaxed flex items-start gap-1.5"><span className="text-indigo-500 dark:text-indigo-400 mt-0.5 shrink-0">✦</span><span>{rule.replace(/^- /, '')}</span></li>
                            ))}
                          </ul>
                        </div>
                      </details>
                    )}
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <p className="text-[10px] text-violet-600 dark:text-violet-400 font-semibold uppercase tracking-wide flex items-center gap-1"><Zap className="h-3 w-3" />Agent 成功解析底层过滤规则：</p>
                        <div className="flex items-center gap-2">
                          <button onClick={handleSubscribe} className="flex items-center gap-1 text-[9px] text-muted-foreground hover:text-primary transition-colors bg-secondary/50 px-1.5 py-0.5 rounded border border-border/30 outline-none"><BellRing className="h-2.5 w-2.5" /> 订阅策略</button>
                          <button onClick={() => setShowRawDsl(!showRawDsl)} className="flex items-center gap-1 text-[9px] text-muted-foreground hover:text-violet-500 transition-colors bg-secondary/50 px-1.5 py-0.5 rounded border border-border/30 outline-none"><Code2 className="h-2.5 w-2.5" /> {showRawDsl ? '收起源码' : '查看源码'}</button>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {data.markets && data.markets.length > 0 && (<span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 shadow-sm">市场: {data.markets.map((m: string) => ({ 'US': '美股', 'HK': '港股', 'SH': '沪股', 'SZ': '深股', 'CN': 'A股' }[m.toUpperCase()] || m)).join(', ')}</span>)}
                        {data.exclude_st && (<span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 shadow-sm">剔除 ST / 退市</span>)}
                        {data.filters && data.filters.map((f: any, idx: number) => {
                          const fieldName = getZhLabel(f.field?.toLowerCase()) || f.field;
                          const formatVal = (v: any) => { let isNum = typeof v === 'number'; let numVal = v; if (!isNum && typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v))) { isNum = true; numVal = Number(v); } if (!isNum) return v; const fieldStr = String(f.field).toUpperCase(); const isPureRatio = ['CURRENT_RATIO', 'QUICK_RATIO', 'PROPERTY_RATIO', 'EQUITY_MULTIPLIER'].some(k => fieldStr.includes(k)); const isPct = !isPureRatio && ['RATIO', 'PCT', 'ROE', 'ROA', 'MARGIN', 'COVER', 'YIELD', 'AMPLITUDE', 'RATE', 'PERCENTILE', 'PRICE_TO_52W'].some(k => fieldStr.includes(k)); if (isPureRatio) return numVal.toFixed(2); if (isPct) return +(numVal * 100).toFixed(2) + '%'; const absVal = Math.abs(numVal); if (absVal >= 1e12) return +(numVal / 1e12).toFixed(2) + '万亿'; if (absVal >= 1e8) return +(numVal / 1e8).toFixed(2) + '亿'; if (absVal >= 1e4) return +(numVal / 1e4).toFixed(2) + '万'; return +(numVal.toFixed(3)); };
                          const minV = f.min !== undefined ? f.min : f.min_value; const maxV = f.max !== undefined ? f.max : f.max_value; let valStr = '';
                          if (minV !== undefined && maxV !== undefined) valStr = `${formatVal(minV)} ~ ${formatVal(maxV)}`; else if (minV !== undefined) valStr = `≥ ${formatVal(minV)}`; else if (maxV !== undefined) valStr = `≤ ${formatVal(maxV)}`; else if (f.value !== undefined) valStr = `= ${Array.isArray(f.value) ? f.value.join(', ') : f.value}`;
                          const termStr = (f.type === 'financial' && f.term && f.term !== 'ANNUAL') ? ` (${f.term})` : '';
                          if (f.type === 'exclude_plate') return (<span key={idx} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 shadow-sm">剔除板块: {valStr.replace('= ', '')}</span>);
                          return (<span key={idx} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-violet-500/10 text-violet-700 dark:text-violet-300 border border-violet-500/20 shadow-sm">{fieldName}{termStr}: {valStr}</span>);
                        })}
                      </div>
                      {showRawDsl && (<div className="mt-2.5 p-2 bg-black/40 rounded-md border border-border/40 overflow-x-auto custom-scrollbar animate-in fade-in slide-in-from-top-1 shadow-inner"><pre className="text-[10px] text-violet-300/80 font-mono leading-relaxed">{JSON.stringify(data, null, 2)}</pre></div>)}
                    </div>
                  </div>
                );
              } catch (e) {
                return (
                  <div>
                    <p className="text-[10px] text-violet-600 dark:text-violet-400 font-semibold uppercase tracking-wide flex items-center gap-1 mb-1.5"><Zap className="h-3 w-3" />Agent 成功解析底层过滤规则：</p>
                    <code className="text-xs font-mono text-violet-700 dark:text-violet-300 block leading-relaxed transition-colors duration-300">{dslQuery}</code>
                  </div>
                );
              }
            })()}
          </div>
        )}
      </div>
      {(isLoading || progress > 0) && (<div className="absolute bottom-0 left-0 right-0 h-[3px] bg-secondary/30"><div className="h-full bg-primary shadow-[0_0_10px_rgba(var(--primary),0.8)] ease-out" style={{ width: `${progress}%`, transition: progress === 100 ? 'width 0.4s ease-out' : 'width 0.15s linear' }} /></div>)}
    </div>
  )
}